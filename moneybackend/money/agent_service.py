import ast
import base64
import json
from decimal import Decimal, DivisionByZero, InvalidOperation
from urllib import error, request

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.utils import timezone
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from rest_framework.test import APIClient

from mcp_gateway.domain_tools import (
    register_domain_tools,
    reset_agent_api_executor,
    set_agent_api_executor,
)


AGENT_MAX_STEPS = 8
AGENT_MAX_HISTORY_MESSAGES = 20
AGENT_MAX_TOOL_RESULT_CHARS = 50_000

_agent_mcp = FastMCP('FrontMoney web agent tools')
register_domain_tools(_agent_mcp)


def _calculate_decimal_expression(expression):
    operators = {
        ast.Add: lambda left, right: left + right,
        ast.Sub: lambda left, right: left - right,
        ast.Mult: lambda left, right: left * right,
        ast.Div: lambda left, right: left / right,
    }

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError('Разрешены только числа, скобки и операции +, -, *, /.')

    normalized = str(expression or '').strip().replace(',', '.')
    if not normalized or len(normalized) > 200:
        raise ValueError('Передайте короткое арифметическое выражение.')
    try:
        return evaluate(ast.parse(normalized, mode='eval'))
    except (SyntaxError, DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError('Некорректное арифметическое выражение.') from exc


@_agent_mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
))
def calculate(expression: str):
    """Calculate an exact decimal arithmetic expression without changing financial data."""
    result = _calculate_decimal_expression(expression)
    return {'expression': expression, 'result': format(result, 'f')}


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def agent_tool_definitions():
    definitions = []
    for tool in _agent_mcp._tool_manager.list_tools():
        definitions.append({
            'type': 'function',
            'function': {
                'name': tool.name,
                'description': tool.description or tool.name,
                'parameters': tool.parameters,
            },
        })
    return definitions


def _is_read_only_tool(tool):
    return bool(tool.annotations and tool.annotations.readOnlyHint)


def _internal_api_request(user, method, path, *, query=None, payload=None):
    client = APIClient()
    client.force_authenticate(user)
    method = method.upper()
    if method == 'GET':
        response = client.get(path, data=query or {})
    elif method == 'DELETE':
        response = client.delete(path, data=payload or {}, format='json')
    else:
        response = client.generic(
            method,
            path,
            data=json.dumps(payload or {}, ensure_ascii=False),
            content_type='application/json',
        )
    try:
        data = response.json() if response.content else None
    except (TypeError, ValueError):
        data = response.content.decode('utf-8', errors='replace')[:4000]
    return {'status': response.status_code, 'data': data}


async def _execute_agent_tool_async(user, tool, arguments):
    async def executor(method, path, *, query=None, payload=None):
        return await sync_to_async(_internal_api_request, thread_sensitive=True)(
            user,
            method,
            path,
            query=query,
            payload=payload,
        )

    token = set_agent_api_executor(executor)
    try:
        return await tool.run(arguments, convert_result=False)
    finally:
        reset_agent_api_executor(token)


def execute_agent_tool(user, tool_name, arguments):
    tool = _agent_mcp._tool_manager.get_tool(tool_name)
    if tool is None:
        raise ValueError(f'Неизвестный tool: {tool_name}')
    return _json_safe(async_to_sync(_execute_agent_tool_async)(user, tool, arguments))


def validate_agent_tool_call(tool_name, arguments):
    tool = _agent_mcp._tool_manager.get_tool(tool_name)
    if tool is None:
        raise ValueError(f'Неизвестный tool: {tool_name}')
    validated = tool.fn_metadata.arg_model.model_validate(arguments)
    return tool, _json_safe(validated.model_dump())


class OpenRouterToolAgent:
    def __init__(self, api_key, model_name):
        self.api_key = api_key
        self.model_name = model_name
        self.tools = agent_tool_definitions()

    def run(self, *, user, text=None, image_bytes=None, image_mime_type=None, history=None):
        messages = [{
            'role': 'system',
            'content': (
                'Ты умный финансовый ассистент FrontMoney. Отвечай пользователю по-русски. '
                f'Текущая дата: {timezone.localdate().isoformat()}. '
                'Ты напрямую видишь запрос и историю диалога. Используй доступные tools только '
                'когда нужны данные приложения или действие. Для обычных вопросов, приветствий '
                'и вопросов о своей работе отвечай самостоятельно без tool. Не выдумывай данные. '
                'Для арифметики всегда используй calculate. Фразы «отними», «сложи», «посчитай», '
                '«покажи результат» и «покажи разницу» считай просьбой о вычислении, если пользователь '
                'явно не попросил «создай расход», «спиши», «запиши операцию» или другое изменение данных. '
                'Гипотетический расчет разрешен даже при отрицательном результате: покажи формулу и число, '
                'не отказывай из-за недостаточного остатка. Учитывай последнее уточнение пользователя и '
                'не повторяй предыдущий ответ, если он просит результат, разницу или исправление. '
                'Перед действиями находи UUID через read-only tools. Все tools, меняющие данные, '
                'сервер не выполнит сразу: он вернет requires_confirmation=true. Объясни пользователю, '
                'что именно подготовлено, и попроси подтвердить. Никогда не утверждай, что изменение '
                'выполнено, пока tool_result не содержит executed=true.'
            ),
        }]
        messages.extend(self._sanitize_history(history or []))
        user_content = [{'type': 'text', 'text': text or 'Проанализируй приложенное изображение.'}]
        if image_bytes:
            user_content.append({
                'type': 'image_url',
                'image_url': {
                    'url': (
                        f'data:{image_mime_type or "image/png"};base64,'
                        f'{base64.b64encode(image_bytes).decode("ascii")}'
                    ),
                },
            })
        messages.append({'role': 'user', 'content': user_content})

        pending_calls = []
        trace = []
        for _ in range(AGENT_MAX_STEPS):
            message = self._request_message(messages, tools=self.tools)
            tool_calls = message.get('tool_calls') or []
            if not tool_calls:
                return {
                    'reply_text': str(message.get('content') or '').strip() or 'Готово.',
                    'pending_calls': pending_calls,
                    'tool_trace': trace,
                }

            messages.append({
                'role': 'assistant',
                'content': message.get('content'),
                'tool_calls': tool_calls,
            })
            for tool_call in tool_calls:
                function = tool_call.get('function') or {}
                tool_name = function.get('name') or ''
                try:
                    arguments = json.loads(function.get('arguments') or '{}')
                    tool, arguments = validate_agent_tool_call(tool_name, arguments)
                    if _is_read_only_tool(tool):
                        result = execute_agent_tool(user, tool_name, arguments)
                        tool_result = {'executed': True, 'result': result}
                        trace.append({'name': tool_name, 'kind': 'read', 'arguments': arguments})
                    else:
                        pending_call = {'name': tool_name, 'arguments': arguments}
                        if pending_call not in pending_calls:
                            pending_calls.append(pending_call)
                        tool_result = {
                            'executed': False,
                            'requires_confirmation': True,
                            'queued_call': pending_call,
                        }
                        trace.append({'name': tool_name, 'kind': 'write_pending', 'arguments': arguments})
                except Exception as exc:
                    tool_result = {'executed': False, 'error': str(exc)}
                    trace.append({'name': tool_name, 'kind': 'error', 'error': str(exc)})

                serialized_result = json.dumps(tool_result, ensure_ascii=False, default=str)
                if len(serialized_result) > AGENT_MAX_TOOL_RESULT_CHARS:
                    serialized_result = json.dumps({
                        'truncated': True,
                        'preview': serialized_result[:AGENT_MAX_TOOL_RESULT_CHARS],
                    }, ensure_ascii=False)
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_call.get('id') or tool_name,
                    'content': serialized_result,
                })

        return {
            'reply_text': 'Не удалось завершить запрос за допустимое число шагов.',
            'pending_calls': pending_calls,
            'tool_trace': trace,
        }

    def complete_after_confirmation(self, *, original_text, executed_results):
        messages = [
            {
                'role': 'system',
                'content': (
                    'Ты финансовый ассистент FrontMoney. Пользователь подтвердил изменения, '
                    'и tools уже выполнены. Кратко и точно сообщи результат по-русски. '
                    'Не добавляй фактов, которых нет в результатах.'
                ),
            },
            {
                'role': 'user',
                'content': (
                    f'Исходный запрос: {original_text}\n'
                    f'Результаты tools: {json.dumps(executed_results, ensure_ascii=False, default=str)}'
                ),
            },
        ]
        message = self._request_message(messages, tools=None)
        return str(message.get('content') or '').strip() or 'Изменения выполнены.'

    def _sanitize_history(self, history):
        sanitized = []
        for item in history[-AGENT_MAX_HISTORY_MESSAGES:]:
            if not isinstance(item, dict) or item.get('role') not in {'user', 'assistant'}:
                continue
            content = str(item.get('content') or '').strip()
            if content:
                sanitized.append({'role': item['role'], 'content': content[:8000]})
        return sanitized

    def _request_message(self, messages, *, tools):
        payload = {
            'model': self.model_name,
            'messages': messages,
            'temperature': 0.1,
            'max_tokens': getattr(settings, 'AI_OPENROUTER_MAX_TOKENS', 4096),
            'provider': {'allow_fallbacks': True},
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        raw = self._request(payload)
        try:
            return raw['choices'][0]['message']
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError('OpenRouter response does not contain a chat message.') from exc

    def _request(self, payload):
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        site_url = getattr(settings, 'AI_OPENROUTER_SITE_URL', '')
        app_name = getattr(settings, 'AI_OPENROUTER_APP_NAME', '')
        if site_url:
            headers['HTTP-Referer'] = site_url
        if app_name:
            headers['X-Title'] = app_name
        http_request = request.Request(
            getattr(settings, 'AI_OPENROUTER_BASE_URL'),
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST',
        )
        try:
            with request.urlopen(http_request, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'OpenRouter agent request failed: {error_body or exc.reason}') from exc
        except error.URLError as exc:
            raise ValueError(f'OpenRouter agent request failed: {exc.reason}') from exc
