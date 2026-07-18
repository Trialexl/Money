import base64
from datetime import timedelta
import hashlib
import json
import mimetypes
import re
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from rest_framework import permissions, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from drf_spectacular.utils import extend_schema

from .ai_service import AiOperationService, FINAL_CONFIRMATION_FIELD
from .models import *
from .serializers import *


class AiAssistantViewSet(viewsets.ViewSet):
    operation_service_class = AiOperationService
    serializer_class = AiAssistantExecuteSerializer

    def get_permissions(self):
        if getattr(self, 'action', None) == 'telegram_webhook':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_operation_service(self):
        return self.operation_service_class()

    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'telegram_webhook':
            return AiAssistantTelegramWebhookSerializer
        if getattr(self, 'action', None) == 'telegram_link_token':
            return TelegramLinkTokenResponseSerializer
        return self.serializer_class

    def _normalize_duplicate_text(self, text):
        if not text:
            return ''
        return re.sub(r'\s+', ' ', text.strip().lower().replace('ё', 'е'))

    def _build_input_fingerprint(self, *, source, actor_key, text, image_bytes, wallet_id=None):
        payload = {
            'source': source,
            'actor_key': actor_key,
            'text': self._normalize_duplicate_text(text),
            'image_sha256': hashlib.sha256(image_bytes).hexdigest() if image_bytes else '',
            'wallet_id': str(wallet_id) if wallet_id else '',
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest(), payload['text'], payload['image_sha256']

    def _serialize_ai_result_for_storage(self, result):
        payload = dict(result)
        parsed = payload.get('parsed')
        if isinstance(parsed, dict):
            payload['parsed'] = self._serialize_result_parsed_payload(parsed)
        return payload

    def _serialize_result_parsed_payload(self, parsed):
        if not isinstance(parsed, dict):
            return {}
        if parsed.get('batch') and isinstance(parsed.get('items'), list):
            return self.get_operation_service().serialize_normalized_batch(parsed)
        if 'wallet_id' in parsed:
            return parsed

        normalized_keys = {
            'intent',
            'confidence',
            'amount',
            'wallet',
            'wallet_from',
            'wallet_to',
            'cash_flow_item',
            'comment',
            'include_in_budget',
            'occurred_at',
            'operation_sign',
            'raw',
        }
        if any(key in parsed for key in normalized_keys):
            return self.get_operation_service().serialize_normalized(parsed)

        return parsed

    def _build_response_payload(self, result):
        return self._serialize_ai_result_for_storage(result)

    def _build_pending_context(self, *, result, input_text='', image_bytes=None, image_mime_type=None):
        parsed = result.get('parsed') or {}
        if not (
            isinstance(parsed, dict)
            and parsed.get('batch')
            and parsed.get('image_based')
            and image_bytes
        ):
            return {}

        return {
            'source_text': input_text or '',
            'image_mime_type': image_mime_type or 'image/jpeg',
            'image_base64': base64.b64encode(image_bytes).decode('ascii'),
        }

    def _load_duplicate_result(self, processed_input):
        return self._load_processed_result(processed_input, annotate_duplicate=True)

    def _load_processed_result(self, processed_input, *, annotate_duplicate):
        payload = dict(processed_input.response_payload)
        if annotate_duplicate:
            payload['status'] = 'duplicate'
            if payload.get('reply_text'):
                payload['reply_text'] = f'Повторный ввод обнаружен. {payload["reply_text"]}'
            else:
                payload['reply_text'] = 'Повторный ввод обнаружен.'
        return payload

    def _semantic_fingerprint_from_result(self, result):
        parsed = result.get('parsed') or {}
        if isinstance(parsed, dict) and parsed.get('batch') and isinstance(parsed.get('items'), list):
            items_payload = []
            for item in parsed.get('items', []):
                if not isinstance(item, dict):
                    continue
                wallet = item.get('wallet')
                wallet_from = item.get('wallet_from')
                wallet_to = item.get('wallet_to')
                cash_flow_item = item.get('cash_flow_item')
                items_payload.append({
                    'intent': item.get('intent'),
                    'amount': str(item.get('amount') or ''),
                    'wallet_id': str(getattr(wallet, 'id', '')) if wallet else '',
                    'wallet_from_id': str(getattr(wallet_from, 'id', '')) if wallet_from else '',
                    'wallet_to_id': str(getattr(wallet_to, 'id', '')) if wallet_to else '',
                    'cash_flow_item_id': str(getattr(cash_flow_item, 'id', '')) if cash_flow_item else '',
                    'occurred_at_minute': (
                        item['occurred_at'].replace(second=0, microsecond=0).isoformat()
                        if item.get('occurred_at') else ''
                    ),
                })
            if not items_payload:
                return ''
            return hashlib.sha256(
                json.dumps({
                    'intent': result.get('intent'),
                    'items': items_payload,
                }, sort_keys=True, ensure_ascii=False).encode('utf-8')
            ).hexdigest()

        wallet = parsed.get('wallet')
        wallet_from = parsed.get('wallet_from')
        wallet_to = parsed.get('wallet_to')
        cash_flow_item = parsed.get('cash_flow_item')
        payload = {
            'intent': result.get('intent'),
            'amount': str(parsed.get('amount') or ''),
            'wallet_id': str(getattr(wallet, 'id', '')) if wallet else '',
            'wallet_from_id': str(getattr(wallet_from, 'id', '')) if wallet_from else '',
            'wallet_to_id': str(getattr(wallet_to, 'id', '')) if wallet_to else '',
            'cash_flow_item_id': str(getattr(cash_flow_item, 'id', '')) if cash_flow_item else '',
            'occurred_at_minute': (
                parsed['occurred_at'].replace(second=0, microsecond=0).isoformat()
                if parsed.get('occurred_at') else ''
            ),
        }
        if not any(payload.values()):
            return ''
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest()

    def _recent_duplicate(self, *, source, fingerprint, user=None, telegram_binding=None):
        threshold = timezone.now() - timedelta(
            seconds=getattr(settings, 'AI_DUPLICATE_WINDOW_SECONDS', 600)
        )
        queryset = AiProcessedInput.objects.filter(
            source=source,
            fingerprint=fingerprint,
            created_at__gte=threshold,
        ).order_by('-created_at')

        if user is not None:
            queryset = queryset.filter(user=user)
        if telegram_binding is not None:
            queryset = queryset.filter(telegram_binding=telegram_binding)
        return queryset.first()

    def _recent_semantic_duplicate(self, *, source, semantic_fingerprint, user=None, telegram_binding=None):
        if not semantic_fingerprint:
            return None
        threshold = timezone.now() - timedelta(
            seconds=getattr(settings, 'AI_DUPLICATE_WINDOW_SECONDS', 600)
        )
        queryset = AiProcessedInput.objects.filter(
            source=source,
            semantic_fingerprint=semantic_fingerprint,
            created_at__gte=threshold,
        ).order_by('-created_at')
        if user is not None:
            queryset = queryset.filter(user=user)
        if telegram_binding is not None:
            queryset = queryset.filter(telegram_binding=telegram_binding)
        return queryset.first()

    def _store_processed_input(
        self,
        *,
        source,
        fingerprint,
        normalized_text,
        image_sha256,
        wallet_id_hint,
        result,
        user=None,
        telegram_binding=None,
        telegram_update_id=None,
    ):
        if result.get('status') != 'created':
            return

        semantic_fingerprint = self._semantic_fingerprint_from_result(result)
        AiProcessedInput.objects.create(
            source=source,
            user=user,
            telegram_binding=telegram_binding,
            telegram_update_id=telegram_update_id,
            fingerprint=fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=wallet_id_hint,
            status=AiProcessedInput.STATUS_CREATED,
            response_payload=self._serialize_ai_result_for_storage(result),
        )

    def _create_audit_log(
        self,
        *,
        source,
        result,
        input_text='',
        image_sha256='',
        user=None,
        telegram_binding=None,
        processed_input=None,
        pending_confirmation=None,
        confirmed_fields=None,
    ):
        parsed = result.get('parsed') or {}
        normalized_payload = self._serialize_result_parsed_payload(parsed)
        AiAuditLog.objects.create(
            source=source,
            user=user,
            telegram_binding=telegram_binding,
            processed_input=processed_input,
            pending_confirmation=pending_confirmation,
            provider=result.get('provider', ''),
            input_text=input_text or '',
            image_sha256=image_sha256 or '',
            raw_provider_payload=parsed.get('raw', {}) if isinstance(parsed, dict) else {},
            normalized_payload=normalized_payload,
            final_response_payload=self._serialize_ai_result_for_storage(result),
            confirmed_fields=confirmed_fields or [],
        )

    def _telegram_sender(self, message):
        sender = message.get('from') or {}
        chat = message.get('chat') or {}
        return {
            'telegram_user_id': sender.get('id'),
            'telegram_chat_id': chat.get('id'),
            'telegram_username': sender.get('username') or '',
            'first_name': sender.get('first_name') or '',
            'last_name': sender.get('last_name') or '',
        }

    def _resolve_telegram_binding(self, message):
        sender = self._telegram_sender(message)
        if not sender['telegram_user_id'] or not sender['telegram_chat_id']:
            return None

        binding, _ = TelegramUserBinding.objects.get_or_create(
            telegram_user_id=sender['telegram_user_id'],
            defaults={
                'telegram_chat_id': sender['telegram_chat_id'],
                'telegram_username': sender['telegram_username'],
                'first_name': sender['first_name'],
                'last_name': sender['last_name'],
            },
        )
        binding.telegram_chat_id = sender['telegram_chat_id']
        binding.telegram_username = sender['telegram_username']
        binding.first_name = sender['first_name']
        binding.last_name = sender['last_name']

        if binding.user_id is None and binding.telegram_username:
            matched_user = get_user_model().objects.filter(
                username=binding.telegram_username,
                is_active=True,
            ).first()
            if matched_user:
                binding.user = matched_user
                binding.linked_at = timezone.now()

        binding.save()
        return binding

    def _largest_telegram_photo(self, message):
        photos = message.get('photo') or []
        if not photos:
            return None
        return max(
            photos,
            key=lambda item: (item.get('file_size') or 0, item.get('width') or 0, item.get('height') or 0),
        )

    def _telegram_audio_attachment(self, message):
        return message.get('voice') or message.get('audio')

    def _telegram_bot_api_url(self, path, *, query=None, file_download=False):
        token = getattr(settings, 'AI_TELEGRAM_BOT_TOKEN', '')
        if not token:
            raise ValueError('AI_TELEGRAM_BOT_TOKEN is not configured.')

        base_url = getattr(settings, 'AI_TELEGRAM_API_BASE_URL', 'https://api.telegram.org').rstrip('/')
        if file_download:
            url = f'{base_url}/file/bot{token}/{path.lstrip("/")}'
        else:
            url = f'{base_url}/bot{token}/{path.lstrip("/")}'
            if query:
                url = f'{url}?{urlparse.urlencode(query)}'
        return url

    def _download_telegram_file(self, *, file_id):
        if not file_id:
            return None, None, None, None

        file_request = urlrequest.Request(
            self._telegram_bot_api_url('getFile', query={'file_id': file_id}),
            method='GET',
        )
        try:
            with urlrequest.urlopen(file_request, timeout=20) as response:
                file_meta = json.loads(response.read().decode('utf-8'))
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'Telegram getFile failed: {error_body or exc.reason}') from exc
        except urlerror.URLError as exc:
            raise ValueError(f'Telegram getFile failed: {exc.reason}') from exc

        file_result = (file_meta or {}).get('result') or {}
        file_path = file_result.get('file_path')
        if not file_path:
            raise ValueError('Telegram getFile response does not contain file_path.')

        download_request = urlrequest.Request(
            self._telegram_bot_api_url(file_path, file_download=True),
            method='GET',
        )
        try:
            with urlrequest.urlopen(download_request, timeout=20) as response:
                image_bytes = response.read()
                content_type = response.headers.get_content_type() if response.headers else None
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'Telegram file download failed: {error_body or exc.reason}') from exc
        except urlerror.URLError as exc:
            raise ValueError(f'Telegram file download failed: {exc.reason}') from exc

        guessed_content_type, _ = mimetypes.guess_type(file_path)
        resolved_content_type = content_type if content_type and content_type != 'application/octet-stream' else guessed_content_type
        return image_bytes, resolved_content_type or 'application/octet-stream', file_path, file_result.get('file_size')

    def _download_telegram_photo(self, message):
        photo = self._largest_telegram_photo(message)
        if photo is None:
            return None, None

        image_bytes, content_type, _, _ = self._download_telegram_file(file_id=photo.get('file_id'))
        return image_bytes, content_type or 'image/jpeg'

    def _download_telegram_audio(self, message):
        attachment = self._telegram_audio_attachment(message)
        if attachment is None:
            return None, None, None

        file_size = attachment.get('file_size') or 0
        if file_size and file_size > 20 * 1024 * 1024:
            raise ValueError('Telegram не позволяет скачать аудиофайл больше 20 MB через стандартный Bot API.')

        audio_bytes, content_type, file_path, _ = self._download_telegram_file(file_id=attachment.get('file_id'))
        file_name = attachment.get('file_name')
        if not file_name and file_path:
            file_name = file_path.rsplit('/', 1)[-1]
        return audio_bytes, content_type or attachment.get('mime_type') or 'audio/ogg', file_name

    def _build_telegram_photo_error_response(self, error_message):
        return {
            'status': 'needs_confirmation',
            'intent': 'unknown',
            'provider': 'telegram',
            'confidence': 0.0,
            'reply_text': error_message,
            'missing_fields': ['image'],
            'parsed': {'source': 'telegram'},
        }

    def _build_telegram_audio_error_response(self, error_message):
        return {
            'status': 'needs_confirmation',
            'intent': 'unknown',
            'provider': 'telegram',
            'confidence': 0.0,
            'reply_text': error_message,
            'missing_fields': ['audio'],
            'parsed': {'source': 'telegram'},
        }

    def _send_telegram_reply(self, *, binding=None, message=None, result=None):
        if not result:
            return
        reply_text = result.get('reply_text')
        if not reply_text:
            return
        if not getattr(settings, 'AI_TELEGRAM_BOT_TOKEN', ''):
            return

        chat_id = getattr(binding, 'telegram_chat_id', None) if binding is not None else None
        if chat_id is None and message:
            chat_id = (message.get('chat') or {}).get('id')
        if chat_id is None:
            return

        payload = {
            'chat_id': chat_id,
            'text': reply_text,
        }
        if result.get('reply_parse_mode'):
            payload['parse_mode'] = result['reply_parse_mode']
        reply_markup = self._telegram_reply_markup(result)
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup
        message_id = (message or {}).get('message_id')
        if message_id is not None:
            payload['reply_to_message_id'] = message_id

        send_request = urlrequest.Request(
            self._telegram_bot_api_url('sendMessage'),
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urlrequest.urlopen(send_request, timeout=20) as response:
                raw = json.loads(response.read().decode('utf-8'))
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'Telegram sendMessage failed: {error_body or exc.reason}') from exc
        except urlerror.URLError as exc:
            raise ValueError(f'Telegram sendMessage failed: {exc.reason}') from exc

        if not raw.get('ok', False):
            raise ValueError('Telegram sendMessage response is not ok.')

    def _telegram_reply_markup(self, result):
        if not result:
            return None

        status_name = result.get('status')
        if status_name in {'created', 'duplicate', 'balance', 'info'}:
            return {'remove_keyboard': True}

        if status_name != 'needs_confirmation':
            return None

        missing_fields = result.get('missing_fields') or []
        if missing_fields == [FINAL_CONFIRMATION_FIELD]:
            return {
                'keyboard': [
                    [{'text': 'Создать'}],
                    [{'text': '/cancel'}],
                ],
                'resize_keyboard': True,
                'one_time_keyboard': False,
            }

        option_labels = []
        for option_list in (result.get('options') or {}).values():
            for option in option_list or []:
                label = (option or {}).get('label')
                if label and label not in option_labels:
                    option_labels.append(label)

        rows = []
        for index in range(0, min(len(option_labels), 8), 2):
            rows.append([{'text': label} for label in option_labels[index:index + 2]])

        rows.append([{'text': '/cancel'}])
        return {
            'keyboard': rows,
            'resize_keyboard': True,
            'one_time_keyboard': False,
        }

    def _telegram_response(self, *, binding=None, message=None, result=None, http_status=status.HTTP_200_OK):
        self._send_telegram_reply(binding=binding, message=message, result=result)
        return Response(self._build_response_payload(result), status=http_status)

    def _build_unbound_response(self):
        return {
            'status': 'needs_confirmation',
            'intent': 'unknown',
            'provider': 'telegram',
            'confidence': 0.0,
            'reply_text': (
                'Telegram аккаунт пока не привязан. '
                'Сгенерируйте код в web API и отправьте в бота команду /link CODE.'
            ),
            'missing_fields': ['binding'],
            'parsed': {'source': 'telegram'},
        }

    def _build_telegram_help_response(self, *, binding):
        include_link_hint = binding is None or binding.user_id is None
        return self.get_operation_service().build_help_result(
            provider_name='telegram',
            source='telegram',
            include_telegram_link_hint=include_link_hint,
        )

    def _handle_telegram_link_command(self, *, binding, text):
        parts = (text or '').strip().split(maxsplit=1)
        if len(parts) != 2:
            return {
                'status': 'needs_confirmation',
                'intent': 'unknown',
                'provider': 'telegram',
                'confidence': 1.0,
                'reply_text': 'Используйте формат /link CODE.',
                'missing_fields': ['binding'],
                'parsed': {'source': 'telegram'},
            }

        code = parts[1].strip().upper()
        token = TelegramLinkToken.objects.filter(
            code=code,
            is_used=False,
            expires_at__gte=timezone.now(),
        ).select_related('user').first()
        if token is None:
            return {
                'status': 'needs_confirmation',
                'intent': 'unknown',
                'provider': 'telegram',
                'confidence': 1.0,
                'reply_text': 'Код привязки не найден или просрочен.',
                'missing_fields': ['binding'],
                'parsed': {'source': 'telegram'},
            }

        binding.user = token.user
        binding.linked_at = timezone.now()
        binding.save(update_fields=['user', 'linked_at', 'updated_at', 'telegram_chat_id', 'telegram_username', 'first_name', 'last_name'])

        token.is_used = True
        token.used_by_binding = binding
        token.save(update_fields=['is_used', 'used_by_binding'])
        return {
            'status': 'created',
            'intent': 'link_telegram',
            'provider': 'telegram',
            'confidence': 1.0,
            'reply_text': f'Telegram привязан к пользователю {binding.user.username}.',
            'parsed': {'source': 'telegram'},
            'created_object': {
                'model': 'TelegramUserBinding',
                'id': str(binding.id),
                'number': code,
            },
        }

    def _handle_telegram_unlink_command(self, *, binding):
        if binding.user_id is None:
            return self._build_unbound_response()
        username = binding.user.username
        binding.user = None
        binding.linked_at = None
        binding.save(update_fields=['user', 'linked_at', 'updated_at'])
        AiPendingConfirmation.objects.filter(telegram_binding=binding, is_active=True).update(is_active=False)
        return {
            'status': 'created',
            'intent': 'unlink_telegram',
            'provider': 'telegram',
            'confidence': 1.0,
            'reply_text': f'Telegram отвязан от пользователя {username}.',
            'parsed': {'source': 'telegram'},
            'created_object': {
                'model': 'TelegramUserBinding',
                'id': str(binding.id),
                'number': 'UNLINK',
            },
        }

    def _looks_like_new_command(self, text):
        normalized_text = (text or '').strip().lower()
        command_prefixes = (
            'приход',
            'доход',
            'расход',
            'трата',
            'перевод',
            'остаток',
            'остатки',
            'баланс',
            'балансы',
            'бюджет',
            'траты',
            'затраты',
            'списания',
            '/start',
            '/bind',
            '/link',
            '/unlink',
            '/cancel',
        )
        if normalized_text.startswith(command_prefixes):
            return True
        return bool(re.search(r'\b(?:остаток|остатки|баланс|балансы|бюджет|расходы|траты|затраты|списания)\b', normalized_text))

    def _upsert_pending_confirmation(self, *, binding, result, input_context=None):
        if result.get('status') != 'needs_confirmation':
            return

        missing_fields = result.get('missing_fields') or []
        if not missing_fields or any(field in {'intent', 'binding'} for field in missing_fields):
            return

        AiPendingConfirmation.objects.filter(
            telegram_binding=binding,
            is_active=True,
        ).update(is_active=False)

        AiPendingConfirmation.objects.create(
            source=AiPendingConfirmation.SOURCE_TELEGRAM,
            user=binding.user,
            telegram_binding=binding,
            intent=result.get('intent') or 'unknown',
            provider=result.get('provider', ''),
            normalized_payload=self._serialize_result_parsed_payload(result['parsed']),
            missing_fields=missing_fields,
            options_payload=result.get('options') or {},
            context_payload=input_context or {},
            prompt_text=(result.get('reply_text', '') or '')[:255],
        )

    def _close_pending_confirmation(self, pending):
        if pending and pending.is_active:
            pending.is_active = False
            pending.save(update_fields=['is_active', 'updated_at'])

    def _active_web_pending_confirmation(self, user):
        return AiPendingConfirmation.objects.filter(
            source=AiPendingConfirmation.SOURCE_WEB,
            user=user,
            telegram_binding__isnull=True,
            is_active=True,
        ).order_by('-updated_at').first()

    def _upsert_web_pending_confirmation(self, *, user, result, input_context=None):
        if result.get('status') != 'needs_confirmation':
            return None

        missing_fields = result.get('missing_fields') or []
        if not missing_fields or any(field in {'intent', 'binding'} for field in missing_fields):
            return None

        AiPendingConfirmation.objects.filter(
            source=AiPendingConfirmation.SOURCE_WEB,
            user=user,
            telegram_binding__isnull=True,
            is_active=True,
        ).update(is_active=False)

        return AiPendingConfirmation.objects.create(
            source=AiPendingConfirmation.SOURCE_WEB,
            user=user,
            intent=result.get('intent') or 'unknown',
            provider=result.get('provider', ''),
            normalized_payload=self._serialize_result_parsed_payload(result['parsed']),
            missing_fields=missing_fields,
            options_payload=result.get('options') or {},
            context_payload=input_context or {},
            prompt_text=(result.get('reply_text', '') or '')[:255],
        )

    def _web_cancel_result(self, *, request, pending):
        return {
            'status': 'created',
            'intent': 'cancel_confirmation',
            'provider': 'web',
            'confidence': 1.0,
            'reply_text': 'Текущая незавершенная команда отменена.',
            'parsed': {'source': 'web'},
            'created_object': {
                'model': 'AiPendingConfirmation',
                'id': str(pending.id) if pending else str(request.user.pk),
                'number': 'CANCEL',
            },
        }

    def _execute_web_conversation(self, *, request, validated, image, image_bytes):
        service = self.get_operation_service()
        text = validated.get('text') or ''
        wallet_id = validated.get('wallet')
        requested_dry_run = validated.get('dry_run', False)
        image_mime_type = getattr(image, 'content_type', None) if image else None
        pending = self._active_web_pending_confirmation(request.user)

        if text and service.detect_meta_intent(text):
            result = service.process(
                text=text,
                dry_run=True,
                source='web',
                user=request.user,
                conversational=True,
            )
            self._create_audit_log(
                source='web',
                result=result,
                input_text=text,
                user=request.user,
            )
            return Response(self._build_response_payload(result), status=status.HTTP_200_OK)

        if text.strip().lower() == '/cancel':
            self._close_pending_confirmation(pending)
            result = self._web_cancel_result(request=request, pending=pending)
            self._create_audit_log(
                source='web',
                result=result,
                input_text=text,
                user=request.user,
                pending_confirmation=pending,
            )
            return Response(self._build_response_payload(result), status=status.HTTP_200_OK)

        is_new_command = bool(image_bytes) or self._looks_like_new_command(text)
        if pending and not is_new_command:
            confirmed_fields = list(pending.missing_fields)
            result = service.continue_confirmation(
                normalized_payload=pending.normalized_payload,
                missing_fields=pending.missing_fields,
                answer_text=text,
                provider_name=pending.provider or 'web-confirmation',
                dry_run=True,
                options_payload=pending.options_payload,
                confirmation_history=pending.confirmation_history,
                pending_context=pending.context_payload,
                source='web',
                conversational=True,
            )
            pending.confirmation_history = list(pending.confirmation_history) + [{'answer_text': text}]
            if result.get('status') == 'needs_confirmation':
                pending.normalized_payload = self._serialize_result_parsed_payload(result['parsed'])
                pending.missing_fields = result.get('missing_fields') or []
                pending.options_payload = result.get('options') or {}
                pending.prompt_text = (result.get('reply_text', '') or '')[:255]
                pending.save(update_fields=[
                    'normalized_payload',
                    'missing_fields',
                    'options_payload',
                    'prompt_text',
                    'confirmation_history',
                    'updated_at',
                ])
                self._create_audit_log(
                    source='web',
                    result=result,
                    input_text=text,
                    user=request.user,
                    pending_confirmation=pending,
                    confirmed_fields=confirmed_fields,
                )
                return Response(self._build_response_payload(result), status=status.HTTP_200_OK)

            semantic_duplicate = self._recent_semantic_duplicate(
                source='web',
                semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                user=request.user,
            )
            if semantic_duplicate:
                duplicate_result = self._load_duplicate_result(semantic_duplicate)
                self._close_pending_confirmation(pending)
                self._create_audit_log(
                    source='web',
                    result=duplicate_result,
                    input_text=text,
                    user=request.user,
                    processed_input=semantic_duplicate,
                    pending_confirmation=pending,
                    confirmed_fields=confirmed_fields,
                )
                return Response(self._build_response_payload(duplicate_result), status=status.HTTP_200_OK)

            result = service.create_from_normalized(
                normalized=result['parsed'],
                provider_name=result['provider'],
                source='web',
                conversational=True,
            )
            self._close_pending_confirmation(pending)
            fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
                source='web',
                actor_key=f'user:{request.user.pk}',
                text=text,
                image_bytes=None,
                wallet_id=wallet_id,
            )
            self._store_processed_input(
                source='web',
                fingerprint=fingerprint,
                normalized_text=normalized_text,
                image_sha256=image_sha256,
                wallet_id_hint=wallet_id,
                result=result,
                user=request.user,
            )
            created_input = AiProcessedInput.objects.filter(
                source='web',
                fingerprint=fingerprint,
                user=request.user,
            ).order_by('-created_at').first()
            self._create_audit_log(
                source='web',
                result=result,
                input_text=text,
                user=request.user,
                processed_input=created_input,
                pending_confirmation=pending,
                confirmed_fields=confirmed_fields,
            )
            return Response(self._build_response_payload(result), status=status.HTTP_201_CREATED)

        if pending and is_new_command:
            self._close_pending_confirmation(pending)

        fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
            source='web',
            actor_key=f'user:{request.user.pk}',
            text=text,
            image_bytes=image_bytes,
            wallet_id=wallet_id,
        )
        duplicate = self._recent_duplicate(
            source='web',
            fingerprint=fingerprint,
            user=request.user,
        )
        if duplicate:
            duplicate_result = self._load_duplicate_result(duplicate)
            self._create_audit_log(
                source='web',
                result=duplicate_result,
                input_text=text,
                image_sha256=image_sha256,
                user=request.user,
                processed_input=duplicate,
            )
            return Response(self._build_response_payload(duplicate_result), status=status.HTTP_200_OK)

        result = service.process(
            text=text,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            wallet_id=wallet_id,
            dry_run=True,
            source='web',
            user=request.user,
            conversational=True,
        )
        if result.get('status') == 'preview' and not requested_dry_run:
            semantic_duplicate = self._recent_semantic_duplicate(
                source='web',
                semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                user=request.user,
            )
            if semantic_duplicate:
                duplicate_result = self._load_duplicate_result(semantic_duplicate)
                self._create_audit_log(
                    source='web',
                    result=duplicate_result,
                    input_text=text,
                    image_sha256=image_sha256,
                    user=request.user,
                    processed_input=semantic_duplicate,
                )
                return Response(self._build_response_payload(duplicate_result), status=status.HTTP_200_OK)
            result = service.create_from_normalized(
                normalized=result['parsed'],
                provider_name=result['provider'],
                source='web',
                conversational=True,
            )

        pending = self._upsert_web_pending_confirmation(
            user=request.user,
            result=result,
            input_context=self._build_pending_context(
                result=result,
                input_text=text,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            ),
        )
        self._store_processed_input(
            source='web',
            fingerprint=fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=wallet_id,
            result=result,
            user=request.user,
        )
        created_input = AiProcessedInput.objects.filter(
            source='web',
            fingerprint=fingerprint,
            user=request.user,
        ).order_by('-created_at').first()
        self._create_audit_log(
            source='web',
            result=result,
            input_text=text,
            image_sha256=image_sha256,
            user=request.user,
            processed_input=created_input if result.get('status') == 'created' else None,
            pending_confirmation=pending,
        )
        http_status = status.HTTP_201_CREATED if result['status'] == 'created' else status.HTTP_200_OK
        return Response(self._build_response_payload(result), status=http_status)

    @extend_schema(
        request=AiAssistantExecuteSerializer,
        responses={200: AiAssistantResponseSerializer, 201: AiAssistantResponseSerializer},
        description=(
            'AI-ввод операции или запроса на остаток. '
            'Поддерживает текст и изображение. '
            'Используется как backend для web-клиента.'
        ),
    )
    @action(detail=False, methods=['post'], url_path='execute')
    def execute(self, request):
        payload = AiAssistantExecuteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        image = payload.validated_data.get('image')
        image_bytes = image.read() if image else None
        if payload.validated_data.get('conversation'):
            return self._execute_web_conversation(
                request=request,
                validated=payload.validated_data,
                image=image,
                image_bytes=image_bytes,
            )

        wallet_id = payload.validated_data.get('wallet')
        fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
            source='web',
            actor_key=f'user:{request.user.pk}',
            text=payload.validated_data.get('text'),
            image_bytes=image_bytes,
            wallet_id=wallet_id,
        )
        duplicate = self._recent_duplicate(
            source='web',
            fingerprint=fingerprint,
            user=request.user,
        )
        if duplicate:
            return Response(self._build_response_payload(self._load_duplicate_result(duplicate)), status=status.HTTP_200_OK)

        requested_dry_run = payload.validated_data.get('dry_run', False)
        result = self.get_operation_service().process(
            text=payload.validated_data.get('text'),
            image_bytes=image_bytes,
            image_mime_type=getattr(image, 'content_type', None) if image else None,
            wallet_id=wallet_id,
            dry_run=True,
            source='web',
            user=request.user,
        )
        if result.get('status') == 'preview' and not requested_dry_run:
            semantic_duplicate = self._recent_semantic_duplicate(
                source='web',
                semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                user=request.user,
            )
            if semantic_duplicate:
                duplicate_result = self._load_duplicate_result(semantic_duplicate)
                self._create_audit_log(
                    source='web',
                    result=duplicate_result,
                    input_text=payload.validated_data.get('text') or '',
                    image_sha256=image_sha256,
                    user=request.user,
                    processed_input=semantic_duplicate,
                )
                return Response(self._build_response_payload(duplicate_result), status=status.HTTP_200_OK)
            result = self.get_operation_service().create_from_normalized(
                normalized=result['parsed'],
                provider_name=result['provider'],
                source='web',
            )
        self._store_processed_input(
            source='web',
            fingerprint=fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=wallet_id,
            result=result,
            user=request.user,
        )
        created_input = AiProcessedInput.objects.filter(
            source='web',
            fingerprint=fingerprint,
            user=request.user,
        ).order_by('-created_at').first()
        self._create_audit_log(
            source='web',
            result=result,
            input_text=payload.validated_data.get('text') or '',
            image_sha256=image_sha256,
            user=request.user,
            processed_input=created_input if result.get('status') == 'created' else None,
        )
        http_status = status.HTTP_201_CREATED if result['status'] == 'created' else status.HTTP_200_OK
        return Response(self._build_response_payload(result), status=http_status)

    @extend_schema(
        responses={200: TelegramLinkTokenResponseSerializer},
        description='Сгенерировать одноразовый код привязки Telegram-бота к текущему пользователю.',
    )
    @action(detail=False, methods=['post'], url_path='telegram-link-token')
    def telegram_link_token(self, request):
        TelegramLinkToken.objects.filter(
            user=request.user,
            is_used=False,
            expires_at__lt=timezone.now(),
        ).delete()
        token = TelegramLinkToken.objects.create(
            user=request.user,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        return Response(
            {'code': token.code, 'expires_at': token.expires_at},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=AiAssistantTelegramWebhookSerializer,
        responses={200: AiAssistantResponseSerializer},
        description=(
            'Webhook для Telegram-бота. '
            'Принимает text, caption, photo, voice или audio из update и возвращает нормализованный reply.'
        ),
    )
    @action(detail=False, methods=['post'], url_path='telegram-webhook')
    def telegram_webhook(self, request):
        expected_secret = getattr(settings, 'AI_TELEGRAM_BOT_SECRET', '')
        if expected_secret:
            actual_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
            if actual_secret != expected_secret:
                return Response({'detail': 'Invalid Telegram secret token.'}, status=status.HTTP_403_FORBIDDEN)

        payload = AiAssistantTelegramWebhookSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        update_id = payload.validated_data.get('update_id')
        message = payload.validated_data.get('message') or payload.validated_data.get('edited_message') or {}
        binding = self._resolve_telegram_binding(message)
        text = message.get('text') or message.get('caption')
        has_photo = bool(message.get('photo'))
        has_audio = bool(self._telegram_audio_attachment(message))
        effective_text = text
        audio_bytes = None
        audio_mime_type = None
        audio_file_name = None

        if text and self.get_operation_service().detect_meta_intent(text):
            result = self._build_telegram_help_response(binding=binding)
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=text,
                user=binding.user if binding and binding.user_id else None,
                telegram_binding=binding,
            )
            return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        if binding and text and text.strip().lower().startswith('/link'):
            result = self._handle_telegram_link_command(binding=binding, text=text)
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=text,
                user=binding.user,
                telegram_binding=binding,
            )
            return self._telegram_response(
                binding=binding,
                message=message,
                result=result,
                http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
            )

        if binding and text and text.strip().lower().startswith('/unlink'):
            result = self._handle_telegram_unlink_command(binding=binding)
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=text,
                user=binding.user,
                telegram_binding=binding,
            )
            return self._telegram_response(
                binding=binding,
                message=message,
                result=result,
                http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
            )

        if binding is None or binding.user_id is None:
            result = self._build_unbound_response()
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=effective_text or '',
                telegram_binding=binding,
            )
            return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        pending = AiPendingConfirmation.objects.filter(
            telegram_binding=binding,
            is_active=True,
        ).order_by('-updated_at').first()

        existing_update = None
        if update_id is not None:
            existing_update = AiProcessedInput.objects.filter(
                source='telegram',
                telegram_binding=binding,
                telegram_update_id=update_id,
            ).order_by('-created_at').first()
            if existing_update:
                duplicate_result = self._load_duplicate_result(existing_update)
                self._create_audit_log(
                    source='telegram',
                    result=duplicate_result,
                    input_text=effective_text or '',
                    user=binding.user,
                    telegram_binding=binding,
                    processed_input=existing_update,
                )
                return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)

        image_bytes = None
        image_mime_type = None
        if has_photo:
            try:
                image_bytes, image_mime_type = self._download_telegram_photo(message)
            except ValueError as exc:
                result = self._build_telegram_photo_error_response(str(exc))
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=text or '',
                    user=binding.user,
                    telegram_binding=binding,
                )
                return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        if has_audio:
            try:
                audio_bytes, audio_mime_type, audio_file_name = self._download_telegram_audio(message)
                transcript_text = self.get_operation_service().transcribe_audio(
                    audio_bytes=audio_bytes,
                    audio_mime_type=audio_mime_type,
                    file_name=audio_file_name,
                )
            except ValueError as exc:
                result = self._build_telegram_audio_error_response(str(exc))
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=text or '',
                    user=binding.user,
                    telegram_binding=binding,
                )
                return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

            effective_text = (
                f'{text.strip()}\n{transcript_text}'
                if text and text.strip()
                else transcript_text
            )
            if self.get_operation_service().detect_meta_intent(effective_text):
                result = self._build_telegram_help_response(binding=binding)
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=effective_text,
                    user=binding.user,
                    telegram_binding=binding,
                )
                return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        if text and text.strip().lower() == '/cancel':
            self._close_pending_confirmation(pending)
            result = {
                'status': 'created',
                'intent': 'cancel_confirmation',
                'provider': 'telegram',
                'confidence': 1.0,
                'reply_text': 'Текущая незавершенная команда отменена.',
                'parsed': {'source': 'telegram'},
                'created_object': {
                    'model': 'AiPendingConfirmation',
                    'id': str(pending.id) if pending else str(binding.id),
                    'number': 'CANCEL',
                },
            }
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=effective_text or text,
                user=binding.user,
                telegram_binding=binding,
                pending_confirmation=pending,
            )
            return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        is_new_command = has_photo or self._looks_like_new_command(effective_text)

        if pending and not is_new_command:
            result = self.get_operation_service().continue_confirmation(
                normalized_payload=pending.normalized_payload,
                missing_fields=pending.missing_fields,
                answer_text=effective_text,
                provider_name=pending.provider or 'telegram-confirmation',
                dry_run=True,
                options_payload=pending.options_payload,
                confirmation_history=pending.confirmation_history,
                pending_context=pending.context_payload,
                source='telegram',
            )
            pending.confirmation_history = list(pending.confirmation_history) + [{'answer_text': effective_text}]
            if result.get('status') == 'needs_confirmation':
                pending.normalized_payload = self._serialize_result_parsed_payload(result['parsed'])
                pending.missing_fields = result.get('missing_fields') or []
                pending.options_payload = result.get('options') or {}
                pending.prompt_text = (result.get('reply_text', '') or '')[:255]
                pending.save(update_fields=['normalized_payload', 'missing_fields', 'options_payload', 'prompt_text', 'confirmation_history', 'updated_at'])
            else:
                semantic_duplicate = self._recent_semantic_duplicate(
                    source='telegram',
                    semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                    user=binding.user,
                    telegram_binding=binding,
                )
                if semantic_duplicate:
                    duplicate_result = self._load_duplicate_result(semantic_duplicate)
                    self._create_audit_log(
                        source='telegram',
                        result=duplicate_result,
                        input_text=effective_text,
                        user=binding.user,
                        telegram_binding=binding,
                        processed_input=semantic_duplicate,
                        pending_confirmation=pending,
                        confirmed_fields=pending.missing_fields,
                    )
                    self._close_pending_confirmation(pending)
                    return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)
                result = self.get_operation_service().create_from_normalized(
                    normalized=result['parsed'],
                    provider_name=result['provider'],
                    source='telegram',
                )
                self._close_pending_confirmation(pending)
                fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
                    source='telegram',
                    actor_key=f'tg:{binding.telegram_user_id}',
                    text=effective_text,
                    image_bytes=audio_bytes,
                )
                duplicate = self._recent_duplicate(
                    source='telegram',
                    fingerprint=fingerprint,
                    user=binding.user,
                    telegram_binding=binding,
                )
                if duplicate:
                    return self._telegram_response(
                        binding=binding,
                        message=message,
                        result=self._load_duplicate_result(duplicate),
                        http_status=status.HTTP_200_OK,
                    )
                self._store_processed_input(
                    source='telegram',
                    fingerprint=fingerprint,
                    normalized_text=normalized_text,
                    image_sha256=image_sha256,
                    wallet_id_hint=None,
                    result=result,
                    user=binding.user,
                    telegram_binding=binding,
                    telegram_update_id=update_id,
                )
                created_input = AiProcessedInput.objects.filter(
                    source='telegram',
                    fingerprint=fingerprint,
                    telegram_binding=binding,
                ).order_by('-created_at').first()
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=effective_text,
                    image_sha256=image_sha256,
                    user=binding.user,
                    telegram_binding=binding,
                    processed_input=created_input,
                    pending_confirmation=pending,
                    confirmed_fields=pending.missing_fields,
                )
            if result.get('status') == 'needs_confirmation':
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=effective_text,
                    user=binding.user,
                    telegram_binding=binding,
                    pending_confirmation=pending,
                    confirmed_fields=pending.missing_fields,
                )
            return self._telegram_response(
                binding=binding,
                message=message,
                result=result,
                http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
            )

        if pending and is_new_command:
            self._close_pending_confirmation(pending)

        fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
            source='telegram',
            actor_key=f'tg:{binding.telegram_user_id}',
            text=effective_text,
            image_bytes=image_bytes or audio_bytes,
        )
        duplicate = self._recent_duplicate(
            source='telegram',
            fingerprint=fingerprint,
            user=binding.user,
            telegram_binding=binding,
        )
        if duplicate:
            duplicate_result = self._load_duplicate_result(duplicate)
            self._create_audit_log(
                source='telegram',
                result=duplicate_result,
                input_text=effective_text,
                user=binding.user,
                telegram_binding=binding,
                processed_input=duplicate,
            )
            return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)

        result = self.get_operation_service().process(
            text=effective_text,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            dry_run=True,
            source='telegram',
            user=binding.user,
        )
        if result.get('status') == 'preview':
            semantic_duplicate = self._recent_semantic_duplicate(
                source='telegram',
                semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                user=binding.user,
                telegram_binding=binding,
            )
            if semantic_duplicate:
                duplicate_result = self._load_duplicate_result(semantic_duplicate)
                self._create_audit_log(
                    source='telegram',
                    result=duplicate_result,
                    input_text=effective_text,
                    user=binding.user,
                    telegram_binding=binding,
                    processed_input=semantic_duplicate,
                )
                return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)
            result = self.get_operation_service().create_from_normalized(
                normalized=result['parsed'],
                provider_name=result['provider'],
                source='telegram',
            )
        self._upsert_pending_confirmation(
            binding=binding,
            result=result,
            input_context=self._build_pending_context(
                result=result,
                input_text=effective_text,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            ),
        )
        self._store_processed_input(
            source='telegram',
            fingerprint=fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=None,
            result=result,
            user=binding.user,
            telegram_binding=binding,
            telegram_update_id=update_id,
        )
        created_input = AiProcessedInput.objects.filter(
            source='telegram',
            fingerprint=fingerprint,
            telegram_binding=binding,
        ).order_by('-created_at').first()
        self._create_audit_log(
            source='telegram',
            result=result,
            input_text=effective_text,
            image_sha256=image_sha256,
            user=binding.user,
            telegram_binding=binding,
            processed_input=created_input,
            pending_confirmation=AiPendingConfirmation.objects.filter(telegram_binding=binding, is_active=True).order_by('-updated_at').first() if result.get('status') == 'needs_confirmation' else None,
        )
        return self._telegram_response(
            binding=binding,
            message=message,
            result=result,
            http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
        )
