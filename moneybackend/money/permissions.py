from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Кастомное разрешение, которое позволяет:
    - Админам: полный доступ (CRUD)
    - Аутентифицированным пользователям: только чтение
    - Анонимным пользователям: запрет доступа
    """
    
    def has_permission(self, request, view):
        # Запрещаем доступ неаутентифицированным пользователям
        if not request.user.is_authenticated:
            return False
            
        # Админы имеют полный доступ
        if request.user.is_staff:
            return True
            
        # Обычные пользователи только читают
        return request.method in permissions.SAFE_METHODS


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Разрешение, которое позволяет:
    - Админам: полный доступ ко всем объектам
    - Пользователям: доступ только к своим объектам
    """
    
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Админы имеют доступ ко всему
        if request.user.is_staff:
            return True
            
        # Проверяем, есть ли у объекта поле owner/user
        if hasattr(obj, 'user'):
            return obj.user == request.user
        elif hasattr(obj, 'owner'):
            return obj.owner == request.user
            
        # Если нет связи с пользователем - запрещаем
        return False


class IsReadOnlyOrAdmin(permissions.BasePermission):
    """
    Разрешение только для чтения или для админов
    """
    
    def has_permission(self, request, view):
        if request.user.is_staff:
            return True
        return request.method in permissions.SAFE_METHODS 