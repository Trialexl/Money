from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.authentication import TokenAuthentication
from rest_framework import serializers


def _build_validation_candidate(serializer, attrs):
    model_class = serializer.Meta.model
    if not serializer.instance:
        return model_class(**attrs)

    candidate = model_class()
    for field in model_class._meta.fields:
        setattr(candidate, field.attname, getattr(serializer.instance, field.attname))
    for attr_name, value in attrs.items():
        setattr(candidate, attr_name, value)
    return candidate


def _run_model_clean(serializer, attrs):
    candidate = _build_validation_candidate(serializer, attrs)
    try:
        candidate.clean()
    except DjangoValidationError as exc:
        if hasattr(exc, 'message_dict'):
            raise serializers.ValidationError(exc.message_dict)
        raise serializers.ValidationError(exc.messages)


class BackendManagedIdentityMixin:
    sync_writable_fields = ()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        authenticator = getattr(request, 'successful_authenticator', None)
        if isinstance(authenticator, TokenAuthentication):
            for field_name in self.sync_writable_fields:
                field = fields.get(field_name)
                if field is None:
                    continue
                field.read_only = False
                field.required = False
                if isinstance(field, serializers.CharField):
                    field.allow_blank = True
        return fields


class CustomUserSerializer(BackendManagedIdentityMixin, serializers.ModelSerializer):
    sync_writable_fields = ('id',)
    id = serializers.UUIDField(read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = get_user_model()
        fields = ['id', 'username', 'full_name', 'status', 'tax_id', 'is_active', 'password']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _run_model_clean(self, attrs)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = self.Meta.model(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=['password'])
        return user


class ProfileCustomUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ['username', 'full_name', 'status', 'tax_id']


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    detail = serializers.CharField()


class LogoutErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
    detail = serializers.CharField()
