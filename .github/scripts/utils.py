#!/usr/bin/env python
import os
import re
import copy
import string
import yaml
import json
import shutil
import requests
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps
from io import BytesIO
import urllib.parse
from pathlib import Path
from typing import Dict, Any
from config import *
from bs4 import BeautifulSoup


def process_friendly_url(friendly_url, replace = "-"):
    # Удаление специальных символов
    processed_id = re.sub(r'[\/\\?%*:|"<>.,;\'\[\]()&]', '', friendly_url)

    # Замена '+' на '-plus'
    processed_id = processed_id.replace("+", "-plus")

    # Удаление пробелов и приведение к нижнему регистру
    processed_id = processed_id.replace(" ", replace).lower()

    return processed_id


def process_vin_hidden(vin):
    return f"{vin[:5]}-{vin[-4:]}"


# Helper function to process permalink
def process_permalink(vin):
    return f"/cars/{vin[:5]}-{vin[-4:]}/"


def format_html_for_mdx(raw_html):
    """
    Форматирует HTML для MDX, учитывая особенности MDX-парсера:
    - Удаляет теги <p>, так как MDX сам их добавляет
    - Заменяет <br/> на перенос строки
    - Сохраняет форматирующие теги
    - Добавляет пробелы после закрывающих тегов
    - Добавляет пробелы перед открывающими тегами
    - Добавляет пробелы между тегами
    - Добавляет переносы между списками и жирным текстом
    """
    # Проверяем корректность HTML с помощью BeautifulSoup
    soup = BeautifulSoup(raw_html, "html.parser")
    
    # Получаем HTML без форматирования (сохраняет &nbsp;)
    html_output = str(soup)

    # print(html_output)
    
    # Экранируем проблемные символы для MDX
    html_output = html_output.replace('\\', '\\\\')  # Экранируем обратные слеши
    html_output = html_output.replace('{', '\\{')    # Экранируем фигурные скобки
    html_output = html_output.replace('}', '\\}')
    
    # Удаляем теги <p> и </p>, так как MDX сам их добавит
    html_output = re.sub(r'</?p>', '', html_output)
    
    # Заменяем <br/> и <br> на перенос строки
    html_output = re.sub(r'(<br/?>)', r'\1\n', html_output)
    
    # Добавляем <br/> между закрывающим списком и тегом жирности
    html_output = re.sub(r'(</ul>)(<strong>)', r'\1<br/>\2', html_output)
    
    # Добавляем пробел после закрывающего тега, если после него идет буква
    html_output = re.sub(r'(</[^>]+>)([а-яА-Яa-zA-Z])', r'\1 \2', html_output)
    
    # Добавляем пробел перед открывающим тегом, если перед ним буква
    html_output = re.sub(r'([а-яА-Яa-zA-Z])(<[^/][^>]*>)', r'\1 \2', html_output)
    
    # Добавляем пробел между двумя тегами
    html_output = re.sub(r'(>)(<)', r'\1 \2', html_output)
    
    # Добавляем переносы строк для лучшей читаемости
    # 1. Разбиваем на строки по закрывающим тегам </ul>, </li>
    html_output = re.sub(r'(</ul>|</li>)', r'\1\n', html_output)
    
    # 2. Разбиваем на строки по открывающим тегам <ul>, <li>
    html_output = re.sub(r'(<ul>|<li>)', r'\n\1', html_output)
    
    # 3. Удаляем лишние пустые строки
    # html_output = re.sub(r'\n\s*\n', '\n', html_output)
    
    # 4. Удаляем пробелы в начале и конце каждой строки
    html_output = '\n'.join(line.strip() for line in html_output.split('\n'))
    
    return html_output

# Helper function to process description and add it to the body
def process_description(desc_text):
    """
    Обрабатывает текст описания, добавляя HTML-разметку.
    Предотвращает вложенные p-теги и проверяет корректность HTML.
    
    Args:
        desc_text (str): Исходный текст описания
        
    Returns:
        str: Обработанный HTML-текст
    """
    if not desc_text:
        return ""
    
    pretty_html = format_html_for_mdx(desc_text)
    # Разбиваем результат на строки
    lines = pretty_html.split('\n')
    wrapped_lines = []
    for line in lines:
        # Если строка пустая или состоит только из пробелов, добавляем <p>&nbsp;</p>
        if not line.strip():
            wrapped_lines.append('<p>&nbsp;</p>')
            continue
        # Если строка начинается с <ul>, <li>, </ul>, </li>, не оборачиваем в <p>
        if line.lstrip().startswith('<ul>') or line.lstrip().startswith('<li>') or \
           line.lstrip().startswith('</ul>') or line.lstrip().startswith('</li>'):
            wrapped_lines.append(line)
        else:
            # Оборачиваем в <p>...</p>
            wrapped_lines.append(f'<p> {line} </p>')
    # Склеиваем обратно в одну строку с переносами
    result_html = '\n'.join(wrapped_lines)
    return result_html


def createThumbs(image_urls, friendly_url, current_thumbs, thumbs_dir, skip_thumbs=False, count_thumbs=5):
    # Ensure count_thumbs is an integer
    # Convert string or other types to integer, with fallback to default value
    try:
        count_thumbs = int(count_thumbs)
    except (ValueError, TypeError):
        count_thumbs = 5  # Default fallback value
        print(f"⚠️ Warning: count_thumbs could not be converted to integer, using default value 5")

    # print(f"🔍 Отладка создания превью:")
    # print(f"   Количество изображений: {len(image_urls)}")
    # print(f"   Пропуск превью: {skip_thumbs}")
    # print(f"   Директория превью: {thumbs_dir}")

    # Определение относительного пути для возврата
    relative_thumbs_dir = thumbs_dir.replace("public", "")

    # Список для хранения путей к новым или существующим файлам
    new_or_existing_files = []

    # Обработка первых count_thumbs изображений
    for index, img_url in enumerate(image_urls[:count_thumbs]):
        try:
            # print(f"   🔄 Обрабатываю изображение {index + 1}: {img_url}")
            
            # Извлечение имени файла из URL и удаление расширения
            original_filename = os.path.basename(urllib.parse.urlparse(img_url).path)
            filename_without_extension, _ = os.path.splitext(original_filename)
            
            # Получение последних 5 символов имени файла (без расширения)
            last_5_chars = filename_without_extension[-5:]
            
            # Формирование имени файла с учетом последних 5 символов
            output_filename = f"thumb_{friendly_url}_{last_5_chars}_{index}.webp"
            output_path = os.path.join(thumbs_dir, output_filename)
            relative_output_path = os.path.join(relative_thumbs_dir, output_filename)

            # print(f"   📁 Путь к превью: {output_path}")

            # Проверка существования файла
            if not os.path.exists(output_path) and not skip_thumbs:
                # print(f"   ⬇️ Загружаю изображение...")
                # Загрузка и обработка изображения, если файла нет
                response = requests.get(img_url)
                image = Image.open(BytesIO(response.content))
                aspect_ratio = image.width / image.height
                new_width = 360
                new_height = int(new_width / aspect_ratio)
                resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                resized_image.save(output_path, "WEBP")
                # print(f"   ✅ Создано превью: {relative_output_path}")
            # else:
                # print(f"   ⚠️ Файл уже существует: {relative_output_path} или пропущен флагом skip_thumbs: {skip_thumbs}")

            # Добавление относительного пути файла в списки
            new_or_existing_files.append(relative_output_path)
            current_thumbs.append(output_path)  # Здесь сохраняем полный путь для дальнейшего использования
        except Exception as e:
            error_message = f"❌ Ошибка при обработке изображения {img_url}: {e}"
            print_message(error_message, "error")

    return new_or_existing_files


def cleanup_unused_thumbs(current_thumbs, thumbs_dir):
    all_thumbs = [os.path.join(thumbs_dir, f) for f in os.listdir(thumbs_dir)]
    unused_thumbs = [thumb for thumb in all_thumbs if thumb not in current_thumbs]

    for thumb in unused_thumbs:
        os.remove(thumb)
        print(f"Удалено неиспользуемое превью: {thumb}")


def create_child_element(parent, new_element_name, text):
    # Поиск существующего элемента
    old_element = parent.find(new_element_name)
    if old_element is not None:
        parent.remove(old_element)

    # Создаем новый элемент с нужным именем и текстом старого элемента
    new_element = ET.Element(new_element_name)
    new_element.text = str(text)

    # Добавление нового элемента в конец списка дочерних элементов родителя
    parent.append(new_element)


def rename_child_element(parent, old_element_name, new_element_name):
    old_element = parent.find(old_element_name)
    if old_element is not None:
        # Создаем новый элемент с нужным именем и текстом старого элемента
        new_element = ET.Element(new_element_name)
        new_element.text = old_element.text

        # Заменяем старый элемент новым
        parent.insert(list(parent).index(old_element), new_element)
        parent.remove(old_element)


def update_element_text(parent, element_name, new_text):
    element = parent.find(element_name)
    if element is not None:
        element.text = new_text
    else:
        # Ваш код для обработки случая, когда элемент не найден
        print(f"Элемент '{element_name}' не найден.")


def localize_element_text(element):
    translations = {
        # engineType
        "hybrid": "Гибрид",
        "petrol": "Бензин",
        "diesel": "Дизель",
        "petrol_and_gas": "Бензин и газ",
        "electric": "Электро",

        # driveType
        "full_4wd": "Постоянный полный",
        "optional_4wd": "Подключаемый полный",
        "front": "Передний",
        "rear": "Задний",

        # gearboxType
        "robotized": "Робот",
        "variator": "Вариатор",
        "manual": "Механика",
        "automatic": "Автомат",

        # transmission
        "RT": "Робот",
        "CVT": "Вариатор",
        "MT": "Механика",
        "AT": "Автомат",

        # ptsType
        "duplicate": "Дубликат",
        "original": "Оригинал",
        "electronic": "Электронный",

        # bodyColor
        "black": "Черный",
        "white": "Белый",
        "blue": "Синий",
        "gray": "Серый",
        "silver": "Серебряный",
        "brown": "Коричневый",
        "red": "Красный",
        "grey": "Серый",
        "azure": "Лазурный",
        "beige": "Бежевый",
        "Dark grey": "Темно-серый",

        # steeringWheel
        "left": "Левый",
        "right": "Правый",
        "L": "Левый",
        "R": "Правый",

        # bodyType
        "suv": "SUV",

    }

    if element is not None and element.text in translations:
        element.text = translations[element.text]


def join_car_data(car, *elements):
    """
    Builds a string by extracting specified elements from the XML car data.

    Args:
        car (Element): The XML element representing a car.
        *elements (str): Variable number of element names to extract.

    Returns:
        str: The string containing extracted elements (joined by spaces).
    """
    car_parts = []

    for element_name in elements:
        element = car.find(element_name)
        if element is not None and element.text is not None:
            car_parts.append(element.text.strip())

    return " ".join(car_parts)


def convert_to_string(element):
    if element.text is not None:
        element.text = str(element.text)
    for child in element:
        convert_to_string(child)


def avitoColor(color):
    mapping = {
        'бежевый': 'бежевый',
        'бордовый': 'бордовый',
        'белый': 'белый',
        '089/20 белый перламутр': 'белый',
        '070/20 белый перламутр': 'белый',
        'голубой': 'голубой',
        'серо-голубой': 'голубой',
        'желтый': 'желтый',
        'зеленый': 'зеленый',
        'зелёный': 'зеленый',
        'золотой': 'золотой',
        'коричневый': 'коричневый',
        'красный': 'красный',
        'оранжевый': 'оранжевый',
        'пурпурный': 'пурпурный',
        'розовый': 'розовый',
        'серебряный': 'серебряный',
        'серебристый': 'серебряный',
        'серый': 'серый',
        'темно-серый': 'серый',
        'платиновый графит': 'серый',
        '1l1/21 серый хром металл': 'серый',
        '1l1/20': 'серый',
        'синий': 'синий',
        'темно-синий': 'синий',
        'фиолетовый': 'фиолетовый',
        'черный': 'черный',
        'чёрный': 'черный',
        'черный/черный': 'черный',
    }

    # Приводим ключ к нижнему регистру для проверки
    normalized_color = color.lower()
    if normalized_color in mapping:
        return mapping[normalized_color].capitalize()
    else:
        # Логирование ошибки в файл
        error_text = f"Не удается обработать цвет: {color}"
        with open('output.txt', 'a') as file:
            file.write(f"{error_text}\n")
        return color  # Возвращаем оригинальный ключ, если он не найден


def load_price_data(file_path: str = "./src/data/dealer-cars_price.json") -> Dict[str, Dict[str, int]]:
    """
    Загружает данные о ценах из JSON файла.
    
    Args:
        file_path (str): Путь к JSON файлу
        
    Returns:
        Dict[str, Dict[str, int]]: Словарь с ценами по VIN
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        print(f"Ошибка при загрузке файла цен: {str(e)}")
        return {}


def update_car_prices(car, prices_data: Dict[str, Dict[str, int]]) -> None:
    """
    Обновляет цены в XML элементе автомобиля.
    
    Args:
        car: XML элемент автомобиля
        prices_data: Данные о ценах из JSON
    """

    # Проверяем существование элемента vin
    vin_elem = car.find('vin')
    if vin_elem is None or vin_elem.text is None:
        print("Элемент 'vin' отсутствует или пустой")
        return
    
    vin = vin_elem.text
    print(f"🔑 Обрабатываю автомобиль с VIN: {vin}")
    vin_hidden = process_vin_hidden(vin)
    
    # Проверяем существование элемента priceWithDiscount
    price_with_discount_elem = car.find('priceWithDiscount')
    if price_with_discount_elem is None or price_with_discount_elem.text is None:
        print(f"Элемент 'priceWithDiscount' отсутствует или пустой для VIN: {vin}")
        return
    
    try:
        current_sale_price = int(price_with_discount_elem.text)
    except ValueError:
        print(f"Не удалось преобразовать 'priceWithDiscount' в число для VIN: {vin}")
        return

    # Проверяем наличие VIN в данных о ценах
    if vin not in prices_data:
        return
    
    car_prices = prices_data[vin]
    
    # Проверяем наличие необходимых ключей в данных о ценах
    required_keys = ["Конечная цена", "Скидка", "РРЦ"]
    if not all(key in car_prices for key in required_keys):
        print(f"Отсутствуют необходимые ключи в данных о ценах для VIN: {vin}")
        return
    
    final_price = car_prices["Конечная цена"]
    if final_price <= current_sale_price:
        discount = car_prices["Скидка"]
        rrp = car_prices["РРЦ"]
        
        # Безопасно обновляем элементы
        price_with_discount_elem.text = str(final_price)
        
        sale_price_elem = car.find('sale_price')
        if sale_price_elem is not None:
            sale_price_elem.text = str(final_price)
        
        max_discount_elem = car.find('max_discount')
        if max_discount_elem is not None:
            max_discount_elem.text = str(discount)
        
        price_elem = car.find('price')
        if price_elem is not None:
            price_elem.text = str(rrp)


def get_xml_content(filename: str, xml_url: str) -> ET.Element:
    """
    Получает XML контент либо из локального файла, либо по URL.
    
    Args:
        filename: Путь к локальному XML файлу
        xml_url: URL для загрузки XML если локальный файл отсутствует
    
    Returns:
        ET.Element: Корневой элемент XML
    """
    if os.path.exists(filename):
        tree = ET.parse(filename)
        return tree.getroot()
    
    response = requests.get(xml_url)
    response.raise_for_status()
    content = response.content

    # Убрать BOM, если он присутствует
    if content.startswith(b'\xef\xbb\xbf'):
        content = content[3:]

    xml_content = content.decode('utf-8')
    return ET.fromstring(xml_content)


def setup_directories(thumbs_dir: str, cars_dir: str) -> None:
    """
    Создает необходимые директории для работы программы.
    
    Args:
        thumbs_dir: Путь к директории для уменьшенных изображений
        cars_dir: Путь к директории для файлов машин
    """
    if not os.path.exists(thumbs_dir):
        os.makedirs(thumbs_dir)
    
    if os.path.exists(cars_dir):
        shutil.rmtree(cars_dir)
    os.makedirs(cars_dir)


def should_remove_car(car: ET.Element, mark_ids: list, folder_ids: list) -> bool:
    """
    Проверяет, нужно ли удалить машину по заданным критериям.
    
    Args:
        car (ET.Element): XML элемент машины.
        mark_ids (list): Список ID марок для удаления.
        folder_ids (list): Список ID папок для удаления.
    
    Returns:
        bool: True если машину нужно удалить, иначе False.
    """
    def element_in_list(element_names, check_list):
        """
        Проверяет, есть ли значение элемента в заданном списке.
        
        Args:
            element_names (list): Список имен элементов для проверки.
            check_list (list): Список значений для сравнения.
        
        Returns:
            bool: True, если значение элемента есть в check_list.
        """
        for name in element_names:
            try:
                value = car.find(name)
                if value is not None and value.text in check_list:
                    return True
            except Exception as e:
                print(f"Ошибка при обработке элемента '{name}': {e}")
        return False
    
    # Проверяем наличие марки автомобиля
    if mark_ids and element_in_list(['mark_id', 'Make', 'brand'], mark_ids):
        return True
    
    # Проверяем наличие папки автомобиля
    if folder_ids and element_in_list(['folder_id', 'Model', 'model'], folder_ids):
        return True
    
    # Если ни одно условие не выполнено, автомобиль оставляем
    return False

def check_local_files(brand, model, color, vin):
    """Проверяет наличие локальных файлов изображений."""
    folder = get_folder(brand, model, vin)
    if folder:
        color_image = get_color_filename(brand, model, color, vin)
        if color_image:

            thumb_path = os.path.join("img", "models", folder, "colors", color_image)
            thumb_brand_path = os.path.join("img", "models", brand.lower(), folder, "colors", color_image)
        
            # Проверяем, существует ли файл
            if os.path.exists(f"public/{thumb_path}"):
                return f"/{thumb_path}"
            elif os.path.exists(f"public/{thumb_brand_path}"):
                return f"/{thumb_brand_path}"
            else:
                errorText = f"\nvin: <code>{vin}</code>\n<b>Не найден локальный файл</b>\n<pre>{color_image}</pre>\n<code>public/{thumb_path}</code>\n<code>public/{thumb_brand_path}</code>"
                print_message(errorText)
                return "https://cdn.alexsab.ru/errors/404.webp"
        else:
            return "https://cdn.alexsab.ru/errors/404.webp"
    else:
        return "https://cdn.alexsab.ru/errors/404.webp"


def create_file(car, filename, friendly_url, current_thumbs, sort_storage_data, dealer_photos_for_cars_avito, config, existing_files):
    # Проверяем существование элемента vin
    vin_elem = car.find('vin')
    if vin_elem is None or vin_elem.text is None:
        return
    
    vin = vin_elem.text
    vin_hidden = process_vin_hidden(vin)
    
    # Проверяем существование других необходимых элементов
    color_elem = car.find('color')
    if color_elem is None or color_elem.text is None:
        return
    
    folder_id_elem = car.find('folder_id')
    if folder_id_elem is None or folder_id_elem.text is None:
        return
    
    mark_id_elem = car.find('mark_id')
    if mark_id_elem is None or mark_id_elem.text is None:
        return
    # Преобразование цвета
    color = color_elem.text.strip().capitalize()
    model = folder_id_elem.text.strip()
    brand = mark_id_elem.text.strip()

    # Получаем folder и color_image для CDN
    folder = get_folder(brand, model, vin)
    color_image = get_color_filename(brand, model, color, vin)

    thumb = "https://cdn.alexsab.ru/errors/404.webp"
    # Проверка через CDN сервис
    if folder:
        if color_image:
            cdn_path = f"https://cdn.alexsab.ru/b/{brand.lower()}/img/models/{folder}/colors/{color_image}"
            try:
                response = requests.head(cdn_path)
                if response.status_code == 200:
                    thumb = cdn_path
                else:
                    # Если файл не найден в CDN, проверяем локальные файлы
                    errorText = f"\n<b>Не удалось найти файл на CDN</b>. Статус <b>{response.status_code}</b>\n<pre>{color_image}</pre>\n<a href='{cdn_path}'>{cdn_path}</a>"
                    print_message(errorText, 'error')
                    thumb = check_local_files(brand, model, color, vin)
            except requests.RequestException as e:
                # В случае ошибки при проверке CDN, используем локальные файлы
                errorText = f"\nОшибка при проверке CDN: {str(e)}"
                print_message(errorText, 'error')
                thumb = check_local_files(brand, model, color, vin)

    # Forming the YAML frontmatter
    content = "---\n"

    # Check if the VIN exists as a key in sort_storage_data
    if vin in sort_storage_data:
        # If VIN exists, use its order value
        order = sort_storage_data[vin]
    else:
        # If VIN doesn't exist, increment the current order and use it
        sort_storage_data['order'] = sort_storage_data.get('order', 0) + 1
        order = sort_storage_data['order']

    content += f"order: {order}\n"

    # content += "layout: car-page\n"
    total_element = car.find('total')
    if total_element is not None:
        content += f"total: {int(total_element.text)}\n"
    else:
        content += "total: 1\n"
    # content += f"permalink: {friendly_url}\n"
    content += f"vin_list: {vin}\n"
    content += f"vin_hidden: {vin_hidden}\n"

    h1 = join_car_data(car, 'mark_id', 'folder_id', 'modification_id')
    content += f"h1: {h1}\n"

    content += f"breadcrumb: {join_car_data(car, 'mark_id', 'folder_id', 'complectation_name')}\n"

    # Купить {{mark_id}} {{folder_id}} {{modification_id}} {{color}} у официального дилера в {{where}}
    content += f"title: 'Купить {join_car_data(car, 'mark_id', 'folder_id', 'complectation_name', 'modification_id', 'color')} у официального дилера в {config['legal_city_where']}'\n"

    description = (
        f'Купить автомобиль {join_car_data(car, "mark_id", "folder_id")}'
        f'{" " + car.find("year").text + " года выпуска" if car.find("year").text else ""}'
        f'{", комплектация " + car.find("complectation_name").text if car.find("complectation_name").text != None else ""}'
        f'{", цвет - " + car.find("color").text if car.find("color").text != None else ""}'
        f'{", двигатель - " + car.find("modification_id").text if car.find("modification_id").text != None else ""}'
        f' у официального дилера в г. {config["legal_city"]}. Стоимость данного автомобиля {join_car_data(car, "mark_id", "folder_id")} – {car.find("priceWithDiscount").text}'
    )
    content += f"description: '{description}'\n"

    description = ""

    color = car.find('color').text.strip().capitalize()
    encountered_tags = set()  # Создаем множество для отслеживания встреченных тегов

    for child in car:
        # Skip nodes with child nodes (except image_tag) and attributes
        if list(child) and child.tag != f'{config["image_tag"]}s':
            continue
        if child.tag == 'total':
            continue
        if child.tag == 'folder_id':
            content += f"{child.tag}: '{child.text}'\n"
        elif child.tag == f'{config["image_tag"]}s':
            # Извлекаем URL из атрибута 'url' вместо текста элемента
            images = extract_image_urls(child, config['image_tag'])
            # Проверяем наличие дополнительных фотографий в dealer_photos_for_cars_avito
            if vin in dealer_photos_for_cars_avito:
                # Добавляем только уникальные изображения
                new_images = [img for img in dealer_photos_for_cars_avito[vin]['images'] if img not in images]
                images.extend(new_images)
            thumbs_files = createThumbs(images, friendly_url, current_thumbs, config['thumbs_dir'], config['skip_thumbs'], config['count_thumbs'])
            content += f"images: {images}\n"
            content += f"thumbs: {thumbs_files}\n"
        elif child.tag == 'color':
            content += f"{child.tag}: {color}\n"
            content += f"image: {thumb}\n"
        elif child.tag == 'extras' and child.text:
            extras = child.text
            flat_extras = extras.replace('\n', '<br>\n')
            content += f"{child.tag}: |\n"
            for line in flat_extras.split("\n"):
                content += f"  {line}\n"
        elif child.tag == config['description_tag'] and child.text:
            description = f"{child.text}"
            # description = description.replace(':', '').replace('📞', '')
            # Сам тег description добавляется ранее, но мы собираем его содержимое для использования в контенте страницы
            # content += f"content: |\n"
            # for line in flat_description.split("\n"):
                # content += f"  {line}\n"
        elif child.tag == 'equipment' and child.text:
            equipment = f"{child.text}"
            flat_equipment = equipment.replace('\n', '<br>\n').replace(':', '').replace('📞', '')
            content += f"{child.tag}: '{flat_equipment}'\n"
            # content += f"{child.tag}: |\n"
            # for line in flat_equipment.split("\n"):
            #     content += f"  {line}\n"
        else:
            if child.tag in encountered_tags:  # Проверяем, встречался ли уже такой тег
                continue  # Если встречался, переходим к следующей итерации цикла
            encountered_tags.add(child.tag)  # Добавляем встреченный тег в множество
            if child.text:  # Only add if there's content
                content += f"{child.tag}: {format_value(child.text)}\n"

    # Если есть описание из dealer_photos_for_cars_avito, используем его
    if vin in dealer_photos_for_cars_avito and dealer_photos_for_cars_avito[vin]['description'] and description == "":
        description = dealer_photos_for_cars_avito[vin]['description']

    content += "---\n"
    content += process_description(description)

    with open(filename, 'w') as f:
        f.write(content)

    print(f"Создан файл: {filename}")
    existing_files.add(filename)

def format_value(value: str) -> str:
    """
    Форматирует значение в зависимости от наличия специальных символов.
    
    Args:
        value (str): Исходное значение.
        
    Returns:
        str: Отформатированное значение.
    """
    if "'" in value:  # Если есть одинарная кавычка, используем двойные кавычки
        return f'"{value}"'
    elif ":" in value:  # Если есть двоеточие, используем одинарные кавычки
        return f"'{value}'"
    return value

def update_yaml(car, filename, friendly_url, current_thumbs, sort_storage_data, dealer_photos_for_cars_avito, config):

    print(f"Обновление файла: {filename}")
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    # Split the content by the YAML delimiter
    yaml_delimiter = "---\n"
    parts = content.split(yaml_delimiter)

    # If there's no valid YAML block, raise an exception
    if len(parts) < 3:
        raise ValueError("No valid YAML block found in the provided file.")

    # Parse the YAML block
    yaml_block = parts[1].strip()
    data = yaml.safe_load(yaml_block)

    total_element = car.find('total')
    if 'total' in data and total_element is not None:
        try:
            car_total_value = int(total_element.text)
            data_total_value = int(data['total'])
            data['total'] = data_total_value + car_total_value
        except ValueError:
            # В случае, если не удается преобразовать значения в int,
            # можно оставить текущее значение data['total'] или установить его в 0,
            # либо выполнить другое действие по вашему выбору
            pass
    else:
        # Если элемент 'total' отсутствует в одном из источников,
        # можно установить значение по умолчанию для 'total' в data или обработать этот случай иначе
        data['total'] += 1

    run_element = car.find('run')
    if 'run' in data and run_element is not None:
        try:
            car_run_value = int(run_element.text)
            data_run_value = int(data['run'])
            data['run'] = min(data_run_value, car_run_value)
        except ValueError:
            # В случае, если не удается преобразовать значения в int,
            # можно оставить текущее значение data['run'] или установить его в 0,
            # либо выполнить другое действие по вашему выбору
            pass
    else:
        # Если элемент 'run' отсутствует в одном из источников,
        # можно установить значение по умолчанию для 'run' в data или обработать этот случай иначе
        data.setdefault('run', 0)

    priceWithDiscount_element = car.find('priceWithDiscount')
    if 'priceWithDiscount' in data and priceWithDiscount_element is not None:
        try:
            car_priceWithDiscount_value = int(priceWithDiscount_element.text)
            data_priceWithDiscount_value = int(data['priceWithDiscount'])
            data['priceWithDiscount'] = min(data_priceWithDiscount_value, car_priceWithDiscount_value)
            data['sale_price'] = min(data_priceWithDiscount_value, car_priceWithDiscount_value)
            description = (
                f'Купить автомобиль {join_car_data(car, "mark_id", "folder_id")}'
                f'{" " + car.find("year").text + " года выпуска" if car.find("year").text else ""}'
                f'{", комплектация " + car.find("complectation_name").text if car.find("complectation_name").text != None else ""}'
                f'{", цвет - " + car.find("color").text if car.find("color").text != None else ""}'
                f'{", двигатель - " + car.find("modification_id").text if car.find("modification_id").text != None else ""}'
                f' у официального дилера в г. {config["legal_city"]}. Стоимость данного автомобиля {join_car_data(car, "mark_id", "folder_id")} – {car.find("priceWithDiscount").text}'
            )
            data["description"] = description
        except ValueError:
            # В случае, если не удается преобразовать значения в int,
            # можно оставить текущее значение data['priceWithDiscount'] или установить его в 0,
            # либо выполнить другое действие по вашему выбору
            pass
    # else:
        # Если элемент 'priceWithDiscount' отсутствует в одном из источников,
        # можно установить значение по умолчанию для 'priceWithDiscount' в data или обработать этот случай иначе
        # data.setdefault('priceWithDiscount', 0)

    max_discount_element = car.find('max_discount')
    if 'max_discount' in data and max_discount_element is not None:
        try:
            car_max_discount_value = int(max_discount_element.text)
            data_max_discount_value = int(data['max_discount'])
            data['max_discount'] = max(data_max_discount_value, car_max_discount_value)
        except ValueError:
            # В случае, если не удается преобразовать значения в int,
            # можно оставить текущее значение data['max_discount'] или установить его в 0,
            # либо выполнить другое действие по вашему выбору
            pass


    vin = car.find('vin').text
    if vin is not None:
        # Создаём или добавляем строку в список
        data['vin_list'] += ", " + vin

    vin_hidden = process_vin_hidden(vin)
    if vin_hidden is not None:
        # Создаём или добавляем строку в список
        data['vin_hidden'] += ", " + vin_hidden

    unique_id = car.find('unique_id')
    if unique_id is not None:
        if not isinstance(data['unique_id'], str):
            data['unique_id'] = str(data['unique_id'])

        data['unique_id'] += ", " + str(unique_id.text)
    else:
        unique_id = car.find('id')
        if unique_id is not None:
            if not isinstance(data['id'], str):
                data['id'] = str(data['id'])

            data['id'] += ", " + str(unique_id.text)

    if 'order' not in data:
        if vin in sort_storage_data:
            # If VIN exists, use its order value
            order = sort_storage_data[vin]
        else:
            # If VIN doesn't exist, increment the current order and use it
            sort_storage_data['order'] = sort_storage_data.get('order', 0) + 1
            order = sort_storage_data['order']

        data['order'] = order

    images_container = car.find(f"{config['image_tag']}s")
    if images_container is not None:
        images = extract_image_urls(images_container, config['image_tag'])
        # Проверяем наличие дополнительных фотографий в dealer_photos_for_cars_avito
        if vin in dealer_photos_for_cars_avito:
            # Добавляем только уникальные изображения
            new_images = [img for img in dealer_photos_for_cars_avito[vin]['images'] if img not in images]
            images.extend(new_images)
        if len(images) > 0:
            # Удаляем дубликаты из существующего списка
            existing_images = data.get('images', [])
            unique_images = list(dict.fromkeys(existing_images + images))
            data['images'] = unique_images
            # Проверяем, нужно ли добавлять эскизы
            if 'thumbs' not in data or (len(data['thumbs']) < 5):
                thumbs_files = createThumbs(images, friendly_url, current_thumbs, config['thumbs_dir'], config['skip_thumbs'], config['count_thumbs'])
                data.setdefault('thumbs', []).extend(thumbs_files)

    # Convert the data back to a YAML string
    updated_yaml_block = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)

    # Reassemble the content with the updated YAML block
    updated_content = yaml_delimiter.join([parts[0], updated_yaml_block, yaml_delimiter.join(parts[2:])])

    # Save the updated content to the output file
    with open(filename, "w", encoding="utf-8") as f:
        f.write(updated_content)

    return filename


# Создаем последовательность a-z + 0-9
chars = string.ascii_lowercase + string.digits
base = len(chars)  # Основание для системы исчисления (36)

def vin_to_number(vin):
    """Конвертирует последние цифры VIN в число."""
    if not vin[-5:].isdigit():
        raise ValueError("Последние 5 символов VIN должны быть цифрами.")
    
    return int(vin[-5:])  # Преобразуем последние 5 символов VIN в число

def number_to_vin(vin, number):
    """Преобразует число обратно в VIN."""
    new_suffix = str(number).zfill(5)  # Преобразуем число обратно в строку с ведущими нулями
    return vin[:-5] + new_suffix  # Собираем новый VIN

def modify_vin(vin, increment):
    """Изменяет VIN путем увеличения последних цифр."""
    vin_number = vin_to_number(vin)  # Получаем числовое значение последних 5 цифр VIN
    new_vin_number = vin_number + increment  # Увеличиваем на заданное значение
    return number_to_vin(vin, new_vin_number)  # Преобразуем обратно в VIN

def str_to_base36(str):
    """Конвертирует строку STR в число на основе системы с основанием 36."""
    value = 0
    for char in str:
        value = value * base + chars.index(char)  # Преобразуем каждый символ в число
    return value

def base36_to_str(value, length):
    """Конвертирует число обратно в строку STR на основе системы с основанием 36."""
    str = []
    while value > 0:
        str.append(chars[value % base])
        value //= base
    return ''.join(reversed(str)).zfill(length)  # Добавляем нули в начало, если нужно

def increment_str(str, increment):
    """Изменяет STR путем увеличения всей строки на значение increment."""
    str_value = str_to_base36(str)  # Конвертируем STRING в число
    new_str_value = str_value + increment  # Увеличиваем на заданное значение
    return base36_to_str(new_str_value, len(str))  # Преобразуем обратно в строку

def duplicate_car(car, config, n, status="в пути", offset=0):
    """Функция для дублирования элемента 'car' N раз с изменением vin."""
    duplicates = []

    # Проверка наличия обязательных полей 'VIN' и 'Availability'
    try:
        if car.find(config['vin_tag']) is None:
            raise ValueError(f"Элемент 'car' не содержит обязательного поля '{config['vin_tag']}'")
        if car.find(config['availability_tag']) is None:
            raise ValueError(f"Элемент 'car' не содержит обязательного поля '{config['availability_tag']}'")
    except ValueError as e:
        print(f"Ошибка: {e}")
        return duplicates  # Вернем пустой список и продолжим выполнение скрипта
    
    for i in range(n):
        try:
            new_car = copy.deepcopy(car)  # Клонируем текущий элемент car
            
            # Обрабатываем VIN
            vin = new_car.find(config['vin_tag']).text
            new_vin = modify_vin(vin.lower(), offset+i+1)
            new_car.find(config['vin_tag']).text = new_vin.upper()  # Меняем текст VIN
            
            # Обрабатываем unique_id, если он существует
            unique_id_element = new_car.find(config['unique_id_tag'])
            if unique_id_element is not None:
                unique_id = unique_id_element.text
                new_unique_id = increment_str(unique_id, offset + i + 1)  # Изменяем последний символ на i
                unique_id_element.text = new_unique_id  # Меняем текст unique_id
                print(vin, new_vin, unique_id, new_unique_id)
            else:
                print(vin, new_vin, f"${config['unique_id_tag']} отсутствует")
            
            # Обновляем статус
            new_car.find(config['availability_tag']).text = status  # Меняем статус Наличие автомобиля
            duplicates.append(new_car)
        
        except AttributeError as e:
            print(f"Ошибка при обработке элемента: {e}")
    
    return duplicates

def load_env_config(source_type: str, default_config) -> Dict[str, Any]:
    """
    Загружает конфигурацию из переменных окружения.
    Формат переменных:
    CARS_[SOURCE_TYPE]_[PARAM_NAME] = value
    
    Например:
    CARS_AUTORU_REMOVE_MARK_IDS = '["mark1", "mark2"]'
    CARS_AVITO_ELEMENTS_TO_LOCALIZE = '["elem1", "elem2"]'
    """
    prefix = f"CARS_{source_type.upper()}_"
    
    # Маппинг переменных окружения на ключи конфигурации
    env_mapping = {
        f"{prefix}MOVE_VIN_ID_UP": "move_vin_id_up",
        f"{prefix}NEW_ADDRESS": "new_address",
        f"{prefix}NEW_PHONE": "new_phone",
        f"{prefix}REPLACEMENTS": "replacements",
        f"{prefix}ELEMENTS_TO_LOCALIZE": "elements_to_localize",
        f"{prefix}REMOVE_CARS_AFTER_DUPLICATE": "remove_cars_after_duplicate",
        f"{prefix}REMOVE_MARK_IDS": "remove_mark_ids",
        f"{prefix}REMOVE_FOLDER_IDS": "remove_folder_ids"
    }
    
    for env_var, config_key in env_mapping.items():
        if env_var in os.environ:
            try:
                value = json.loads(os.environ[env_var])
                default_config[config_key] = value
            except json.JSONDecodeError:
                print(f"Ошибка при парсинге значения переменной {env_var}")
                # Оставляем значение по умолчанию
    
    return default_config

def load_github_config(source_type: str, github_config: Dict[str, str], default_config) -> Dict[str, Any]:
    """
    Загружает конфигурацию из GitHub репозитория или Gist.
    
    :param source_type: Тип источника (autoru или avito)
    :param github_config: Словарь с настройками GitHub
    :return: Загруженная конфигурация
    """
    if 'GITHUB_TOKEN' in os.environ:
        headers = {'Authorization': f'token {os.environ["GITHUB_TOKEN"]}'}
    else:
        headers = {}

    try:
        if 'gist_id' in github_config:
            # Загрузка из Gist
            gist_url = f"https://api.github.com/gists/{github_config['gist_id']}"
            response = requests.get(gist_url, headers=headers)
            response.raise_for_status()
            gist_data = response.json()
            
            # Ищем файл конфигурации для нужного источника
            for filename, file_data in gist_data['files'].items():
                if source_type in filename.lower():
                    return json.loads(file_data['content'])
                    
        elif 'repo' in github_config and 'path' in github_config:
            # Загрузка из репозитория
            repo = github_config['repo']
            path = github_config['path']
            file_url = f"https://api.github.com/repos/{repo}/contents/{path}/{source_type}.json"
            
            response = requests.get(file_url, headers=headers)
            response.raise_for_status()
            
            content = response.json()['content']
            import base64
            decoded_content = base64.b64decode(content).decode('utf-8')
            return json.loads(decoded_content)
            
    except requests.RequestException as e:
        print(f"Ошибка при загрузке конфигурации из GitHub: {e}")
    except json.JSONDecodeError:
        print("Ошибка при парсинге JSON конфигурации")
    except KeyError as e:
        print(f"Отсутствует обязательный параметр в конфигурации: {e}")
        
    # Возвращаем конфигурацию по умолчанию в случае ошибки
    return default_config

def load_file_config(config_path: str, source_type: str, default_config) -> Dict[str, Any]:
    """
    Загружает конфигурацию из JSON файла.
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get(source_type, default_config)
    except FileNotFoundError:
        print(f"Конфигурационный файл {config_path} не найден. Используются значения по умолчанию.")
        return default_config
    except json.JSONDecodeError:
        print(f"Ошибка при чтении {config_path}. Используются значения по умолчанию.")
        return default_config

def extract_image_urls(images_container, image_tag):
    """
    Универсальная функция для извлечения URL изображений.
    Проверяет сначала атрибут 'url', затем текст элемента.
    
    Args:
        images_container: Контейнер с изображениями
        image_tag: Тег изображения
        
    Returns:
        list: Список URL изображений
    """
    images = []
    for i, img in enumerate(images_container.findall(image_tag)):
        # Сначала пробуем получить URL из атрибута 'url'
        url = img.get('url')
        if url:
            images.append(url)
        else:
            # Если атрибута нет, пробуем получить из текста элемента
            if img.text and img.text.strip():
                url = img.text.strip()
                images.append(url)
            else:
                print(f"  ⚠️ Изображение {i+1}: Не удалось извлечь URL (нет атрибута 'url' и текста)")
    return images
