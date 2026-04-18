from django.db import models


def generate_document_number(prefix, model_class):
    """
    Генерирует уникальный номер документа с префиксом
    
    Args:
        prefix (str): Префикс для номера (например, 'RCP', 'EXP', 'TRF')
        model_class: Класс модели для поиска максимального номера
    
    Returns:
        str: Сгенерированный номер в формате PREFIX001, PREFIX002, etc.
    """
    # Получаем максимальный номер для данного префикса
    max_number = model_class.objects.filter(
        number__startswith=prefix
    ).aggregate(
        max_num=models.Max('number')
    )['max_num']
    
    if max_number:
        # Извлекаем числовую часть и увеличиваем на 1
        try:
            num_part = max_number[len(prefix):]
            next_num = int(num_part) + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    
    # Форматируем номер с ведущими нулями (3 цифры)
    return f"{prefix}{next_num:03d}"


def generate_code(prefix, model_class):
    """
    Генерирует уникальный код справочника с префиксом
    
    Args:
        prefix (str): Префикс для кода (например, 'CFI', 'WLT', 'PRJ')
        model_class: Класс модели для поиска максимального кода
    
    Returns:
        str: Сгенерированный код в формате PREFIX001, PREFIX002, etc.
    """
    # Получаем максимальный код для данного префикса
    max_code = model_class.objects.filter(
        code__startswith=prefix
    ).aggregate(
        max_code=models.Max('code')
    )['max_code']
    
    if max_code:
        # Извлекаем числовую часть и увеличиваем на 1
        try:
            num_part = max_code[len(prefix):]
            next_num = int(num_part) + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    
    # Форматируем код с ведущими нулями (3 цифры)
    return f"{prefix}{next_num:03d}"
