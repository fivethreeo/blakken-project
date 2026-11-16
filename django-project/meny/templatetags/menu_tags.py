from copy import copy

from django import template

from meny.models import ALLERGEN_CHOICES, PAGE_SLUG_SUFFIXES, Menu, MenuPage, menu_page_groups, unique_page_slug, visible_menu_pages

register = template.Library()


@register.simple_tag
def get_menu_by_id(menu_id):
    return Menu.objects.prefetch_related('pages__dishes').get(pk=menu_id)


@register.simple_tag
def get_menu_pages(menu, include_hidden=False):
    authored = list(menu.pages.all())
    visible_ids = {page.pk for page in visible_menu_pages(authored)}
    reserved = {page.slug for page in authored}
    authored_slugs = reserved.copy()
    groups = menu_page_groups(authored)
    category_controls = {}
    for index, group in enumerate(groups):
        movable = group[0].layout != MenuPage.Layout.COVER
        for member in group:
            category_controls[member.pk] = (
                group[0],
                movable and index > 0 and groups[index - 1][0].layout != MenuPage.Layout.COVER,
                movable and index + 1 < len(groups) and groups[index + 1][0].layout != MenuPage.Layout.COVER,
            )
    if not include_hidden:
        authored = [page for page in authored if page.pk in visible_ids]
    pages = []
    for index, original in enumerate(authored):
        page = copy(original)
        page.turnpage_key = str(page.pk)
        category, move_left, move_right = category_controls.get(original.pk, (original, False, False))
        page.turnpage_category_id = category.pk
        page.turnpage_category_slug = category.slug
        page.turnpage_category_name = category.name
        page.turnpage_category_visible = category.is_visible
        page.turnpage_visible = original.pk in visible_ids
        page.turnpage_move_left = move_left
        page.turnpage_move_right = move_right
        page.turnpage_can_add_page = index < len(authored) - 1 and (
            index == 0 or page.layout != MenuPage.Layout.COVER
        )
        page.turnpage_can_add_dish = (
            index not in (0, len(authored) - 1) and page.layout != MenuPage.Layout.COVER
        )
        page.turnpage_dishes = tuple(
            dish for dish in original.dishes.all() if include_hidden or dish.is_visible
        )
        page.turnpage_first_dish_id = page.turnpage_dishes[0].pk if page.turnpage_dishes else None
        page.turnpage_last_dish_id = page.turnpage_dishes[-1].pk if page.turnpage_dishes else None
        pages.append(page)
        if (
            index in (0, len(authored) - 1)
            or page.layout == MenuPage.Layout.COVER
            or not menu.max_per_page
            or not menu.max_per_extra_page
        ):
            continue
        first_limit = menu.max_per_extra_page if page.is_continuation else menu.max_per_page
        dishes = page.turnpage_dishes
        page.turnpage_dishes = dishes[:first_limit]
        base = page.slug
        if page.is_continuation:
            root, _, suffix = base.rpartition('-')
            if root in authored_slugs and (
                suffix in PAGE_SLUG_SUFFIXES or suffix.isdecimal()
            ):
                base = root
        for offset in range(first_limit, len(dishes), menu.max_per_extra_page):
            continuation = copy(page)
            continuation.is_continuation = True
            continuation.slug = unique_page_slug(base, reserved)
            reserved.add(continuation.slug)
            continuation.turnpage_key = f'{page.pk}-{continuation.slug}'
            continuation.turnpage_dishes = dishes[offset:offset + menu.max_per_extra_page]
            if page.layout == MenuPage.Layout.PANORAMA:
                # The panorama spans the first pair, not every overflow page.
                continuation.image = ''
                continuation.layout = MenuPage.Layout.SPLIT
            pages.append(continuation)
    spread_starts = [
        index > 0
        and index + 1 < len(pages) - 1
        and page.layout == MenuPage.Layout.PANORAMA
        and bool(page.image)
        and not pages[index + 1].image
        for index, page in enumerate(pages)
    ]
    has_toc = menu.show_toc and len(pages) >= 4
    page_number = 1 if has_toc else 0
    for index, page in enumerate(pages):
        page.turnpage_background = bool(page.image)
        page.turnpage_spread = spread_starts[index]
        page.turnpage_spread_partner = index > 0 and spread_starts[index - 1]
        if index == 0 or index == len(pages) - 1 or page.turnpage_spread_partner:
            continue
        if page.turnpage_spread:
            if page_number % 2:
                page_number += 1
            page.turnpage_page_number = page_number + 1
            pages[index + 1].turnpage_page_number = page_number + 2
            page_number += 2
        else:
            page.turnpage_page_number = page_number + 1
            page_number += 1
    if page_number % 2:
        page_number += 1
    for page in pages:
        page.turnpage_total = page_number
    return pages


@register.filter
def allergen_labels(dish):
    selected = set(dish.allergens or [])
    return [label for key, label in ALLERGEN_CHOICES if key in selected]
