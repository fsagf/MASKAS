"""
ui/theme.py
Дизайн-система и архитектура токенов Trading Journal Pro (Flet 0.25.2).
Концепция: 'Dark Premium Terminal' (графитово-синяя основа, микро-границы,
точечные свечения, строгая терминальная моно-типографика).

Включает:
- Семантическую цветовую палитру и поверхности разных уровней
- Токены отступов (шкала 4px), радиусов и шрифтов (Inter + JetBrains Mono)
- Глобальный тумблер анимаций ANIMATIONS_ENABLED (Reduced Motion)
- Доступные индикаторы прибыли/убытка (dual-channel: цвет + знаки/стрелки)
- Базовые фабрики терминальных компонентов (карточки, бейджи, оверлеи)
"""

from typing import List, Optional, Union
import flet as ft

# ==============================================================================
# 1. ЦВЕТОВАЯ СИСТЕМА (SURFACES, BORDERS, TEXTS, ACCENTS, SEMANTICS)
# ==============================================================================

# Фоновые слои и поверхности
BG_APP = "#0A0C11"            # Глубокий темный фон приложения (Canvas)
SURFACE_1 = "#10131A"         # Уровень 1: базовые карточки, панели контента
SURFACE_2 = "#161A23"         # Уровень 2: приподнятые панели, hover-состояния строк
SURFACE_3 = "#1D2230"         # Уровень 3: поля ввода, активные кнопки и чипсы
SURFACE_OVERLAY = "#12151E"   # Поверхность модальных окон и выпадающих меню

# Тонкие границы и разделители
BORDER_SUBTLE = "#232938"     # Стандартная микро-граница карточек (1px)
BORDER_HIGHLIGHT = "#343C52"  # Верхняя фаска / подсветка активной границы
BORDER_FOCUS = "#7C5CFF"      # Рамка фокуса поля ввода или активной карточки
GRID_COLOR = "#151922"        # Фоновая координатная сетка графиков

# Типографические контрасты (WCAG AA / AAA)
TEXT_PRIMARY = "#E8EAF0"      # Основной текст (контраст > 12:1 к BG_APP)
TEXT_SECONDARY = "#8B93A7"    # Подписи, метки колонок (контраст > 4.8:1, WCAG AA)
TEXT_MUTED = "#5A6275"        # Плейсхолдеры, отключенные элементы
TEXT_INVERTED = "#0A0C11"     # Текст на ярких акцентных кнопках

# Ключевые акценты
ACCENT_PRIMARY = "#7C5CFF"        # Премиальный фиолетовый акцент
ACCENT_PRIMARY_HOVER = "#8E72FF"  # Состояние наведения акцента
ACCENT_SECONDARY = "#22D3EE"      # Неоновый циан (квант-индикаторы, свечи)
ACCENT_SECONDARY_HOVER = "#38BDF8"# Циан при наведении

# Семантические статусы (Trading Feedback)
PROFIT = "#34D399"            # Изумрудный плюс (прибыль / Long)
PROFIT_DARK = "#059669"       # Темный изумруд для градиента
LOSS = "#FB7185"              # Кораллово-розовый минус (убыток / Short)
LOSS_DARK = "#E11D48"         # Темный коралловый для градиента
WARNING_TILT = "#FBBF24"      # Янтарный (тильт-статус, риск)
COLOR_INDIGO = "#6366F1"      # Индиго (Монте-Карло, квант)
COLOR_PURPLE = "#8B5CF6"      # Фиолетовый (R-Multiple)

# ------------------------------------------------------------------------------
# Обратная совместимость для существующего кода
# ------------------------------------------------------------------------------
BG_SURFACE = SURFACE_1
BG_SURFACE_LIGHT = SURFACE_2
BG_SURFACE_HOVER = SURFACE_2
BORDER_COLOR = BORDER_SUBTLE
BORDER_COLOR_LIGHT = BORDER_HIGHLIGHT
COLOR_ACCENT = ACCENT_PRIMARY
COLOR_CYAN = ACCENT_SECONDARY
COLOR_LONG = PROFIT
COLOR_LONG_DARK = PROFIT_DARK
COLOR_SHORT = LOSS
COLOR_SHORT_DARK = LOSS_DARK
COLOR_AMBER = WARNING_TILT

# ==============================================================================
# 2. ТИПОГРАФИКА И ЛОКАЛЬНЫЕ ШРИФТЫ
# ==============================================================================

# Семейства локальных шрифтов из assets/fonts/ (без внешних сетевых запросов)
FONT_FAMILY = "Inter"
FONT_MONO = "JetBrainsMono, RobotoMono, Consolas, monospace"

# Шкала типографических размеров (8 уровней)
TEXT_XS = 10     # Микро-метки, теги статусов
TEXT_SM = 11     # Подписи, мета-информация, спарклайны
TEXT_BASE = 12   # Обычный текст таблиц и полей ввода
TEXT_MD = 14     # Заголовки карточек, кнопки
TEXT_LG = 16     # Заголовки панелей, названия разделов
TEXT_XL = 20     # Главные заголовки экранов, баланс бэктеста
TEXT_2XL = 28    # Доминирующий Net PnL на Дашборде
TEXT_3XL = 36    # Крупные сводки

# ==============================================================================
# 3. СЕТКА ОТСТУПОВ (4px-based Spacing Scale) И СКРУГЛЕНИЯ
# ==============================================================================

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32

RADIUS_SM = 6     # Микро-чипсы, бейджи
RADIUS_MD = 8     # Кнопки, инпуты, селекторы
RADIUS_LG = 12    # Карточки дашборда, контейнеры
RADIUS_XL = 16    # Модальные окна, инспектор сделки
RADIUS_PILL = 999 # Фильтр-чипсы, pill-бейджи

# ==============================================================================
# 4. АНИМАЦИИ И РЕЖИМ REDUCED MOTION
# ==============================================================================

# Глобальный флаг управления всеми анимациями приложения
ANIMATIONS_ENABLED: bool = True

# Токены длительности анимаций
ANIM_FAST_MS = 140    # Нажатия, hover, смена прозрачности
ANIM_NORMAL_MS = 240  # Переключение экранов, появление карточек
ANIM_SLOW_MS = 380    # Выдвижение бокового инспектора, модалки

# Кривые сглаживания Flet
ANIM_CURVE_OUT = ft.AnimationCurve.EASE_OUT
ANIM_CURVE_IN_OUT = ft.AnimationCurve.EASE_IN_OUT
ANIM_CURVE_CUBIC = ft.AnimationCurve.EASE_OUT_CUBIC


def get_animation(
    duration_ms: int = ANIM_NORMAL_MS,
    curve: ft.AnimationCurve = ANIM_CURVE_OUT,
) -> Optional[ft.Animation]:
    """
    Возвращает объект ft.Animation или None, если анимации отключены пользователем.
    """
    if not ANIMATIONS_ENABLED:
        return None
    return ft.Animation(duration_ms, curve)


# ==============================================================================
# 5. СВЕЧЕНИЯ, ТЕНИ И ВИЗУАЛЬНАЯ ГЛУБИНА
# ==============================================================================

def create_neon_box_shadow(color: str, blur: int = 20, opacity: Union[float, str] = 0.18) -> ft.BoxShadow:
    """
    Создает мягкое свечение вокруг акцентных карточек без резких неоновых пятен.
    Поддерживает как float (0.0..1.0), так и hex-строку ("2E", "1C" и т.д.).
    Использует актуальный синтаксис Flet 0.25.2 ft.Colors.with_opacity.
    """
    norm_opacity: float = 0.18
    if isinstance(opacity, (int, float)):
        norm_opacity = max(0.0, min(1.0, float(opacity)))
    elif isinstance(opacity, str):
        try:
            norm_opacity = max(0.0, min(1.0, int(opacity, 16) / 255.0))
        except ValueError:
            try:
                norm_opacity = max(0.0, min(1.0, float(opacity)))
            except ValueError:
                norm_opacity = 0.18

    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=blur,
        color=ft.Colors.with_opacity(norm_opacity, color),
        offset=ft.Offset(0, 4),
    )


def create_card_border(is_focused: bool = False, accent_color: Optional[str] = None) -> ft.Border:
    """
    Создает стандартную терминальную границу карточки с опциональным акцентом.
    """
    if is_focused:
        border_col = accent_color or ACCENT_PRIMARY
        return ft.border.all(1, border_col)
    return ft.border.all(1, BORDER_SUBTLE)


# ==============================================================================
# 6. БЕЙДЖИ И ДОСТУПНОСТЬ ДЛЯ ДАЛЬТОНИКОВ (DUAL-CHANNEL ACCESSIBILITY)
# ==============================================================================

def create_strategy_badge(tag: str) -> ft.Container:
    """
    Создает минималистичный Outline-бейдж стратегии с контрастным моноширинным текстом.
    """
    clean_tag = (tag or "Общая").strip()
    tag_lower = clean_tag.lower()

    if any(k in tag_lower for k in ["breakout", "пробой"]):
        color = COLOR_PURPLE
    elif any(k in tag_lower for k in ["trend", "тренд"]):
        color = PROFIT
    elif any(k in tag_lower for k in ["scalp", "скальп"]):
        color = WARNING_TILT
    elif any(k in tag_lower for k in ["swing", "свинг"]):
        color = ACCENT_SECONDARY
    else:
        color = TEXT_SECONDARY

    return ft.Container(
        content=ft.Text(
            clean_tag.upper(),
            size=TEXT_XS,
            weight=ft.FontWeight.W_600,
            color=color,
            font_family=FONT_MONO,
        ),
        bgcolor=ft.Colors.with_opacity(0.08, color),
        padding=ft.padding.symmetric(horizontal=8, vertical=2),
        border_radius=RADIUS_PILL,
        border=ft.border.all(1, ft.Colors.with_opacity(0.35, color)),
    )


def create_pnl_badge(direction: str) -> ft.Container:
    """
    Создает бейдж направления позиции с двойным кодированием (иконка + цвет)
    для полной доступности дальтоникам (WCAG).
    """
    is_long = (direction or "").upper() == "LONG"
    color = PROFIT if is_long else LOSS
    dir_str = "LONG" if is_long else "SHORT"
    icon_name = ft.Icons.ARROW_DROP_UP_ROUNDED if is_long else ft.Icons.ARROW_DROP_DOWN_ROUNDED

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(icon_name, size=14, color=color),
                ft.Text(dir_str, size=10, weight=ft.FontWeight.BOLD, color=color, font_family=FONT_MONO),
            ],
            spacing=1,
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.12, color),
        padding=ft.padding.only(left=4, right=8, top=2, bottom=2),
        border_radius=RADIUS_SM,
        border=ft.border.all(1, ft.Colors.with_opacity(0.4, color)),
    )


def format_pnl_value(net_pnl: float, show_sign: bool = True) -> str:
    """
    Форматирует значение PnL со строгим знаком плюс или минус (+$$$ / −$$$).
    """
    sign = "+" if net_pnl > 0 and show_sign else ("−" if net_pnl < 0 and show_sign else "")
    return f"{sign}${abs(net_pnl):,.2f}"


def create_pnl_display(
    net_pnl: float,
    size: int = TEXT_MD,
    bold: bool = True,
    show_arrow: bool = True,
) -> ft.Row:
    """
    Отображает PnL со стрелкой направления (▲ / ▼), знаком и цветом.
    Двойное кодирование обеспечивает читаемость без опоры исключительно на цвет.
    """
    is_win = net_pnl >= 0
    color = PROFIT if is_win else LOSS
    arrow = "▲ " if (is_win and net_pnl > 0) else ("▼ " if net_pnl < 0 else "• ")
    sign = "+" if net_pnl > 0 else ("−" if net_pnl < 0 else "")
    formatted_num = f"{sign}${abs(net_pnl):,.2f}"

    controls: List[ft.Control] = []
    if show_arrow:
        controls.append(
            ft.Text(
                arrow,
                size=size - 2,
                weight=ft.FontWeight.BOLD,
                color=color,
                font_family=FONT_MONO,
            )
        )
    controls.append(
        ft.Text(
            formatted_num,
            size=size,
            weight=ft.FontWeight.BOLD if bold else ft.FontWeight.W_600,
            color=color,
            font_family=FONT_MONO,
        )
    )

    return ft.Row(controls=controls, spacing=0, tight=True)


# ==============================================================================
# 5. ГЛОБАЛЬНЫЙ ПАТЧ РЕНДЕРИНГА ТУЛТИПОВ FLET (0.25.2+)
# ==============================================================================

def patch_flet_chart_tooltips() -> None:
    """
    Патч для Flet 0.25.2: устраняет баг двойного экранирования (JSON-escape) подсказок графиков.
    В Flet PR #4525 Control._before_build_command вызывает _set_attr_json("tooltip", self.tooltip)
    для всех контролов, кроме ['segment', 'bar_chart_rod']. LineChartDataPoint ('p') не был исключен,
    из-за чего Flet упаковывал строку тултипа через json.dumps, а клиентский Flutter fl_chart
    рендерил сырой JSON-строковый литерал с кавычками и экранированным юникодом (\u0442\\\\u0435... вместо 'тест').
    """
    try:
        from flet.core.charts.line_chart_data_point import LineChartDataPoint
        orig_before = LineChartDataPoint._before_build_command

        def patched_before(self):
            orig_tooltip = self.tooltip
            orig_before(self)
            if orig_tooltip is not None:
                self._set_attr("tooltip", str(orig_tooltip))

        LineChartDataPoint._before_build_command = patched_before
    except Exception as ex:
        print(f"[Theme] Warning: Could not patch LineChartDataPoint tooltip: {ex}")


# Применяем патч при импорте темы
patch_flet_chart_tooltips()

