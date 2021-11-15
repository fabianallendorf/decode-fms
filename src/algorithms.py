from typing import Set, Tuple
from src.dataclasses import FormItem, FormItemMetadata
from src.enums import ItemType
from src.parser import FormItemParser
from src.services import FormSession
from src.types import FormID, FormItems, FormMetadata, UpdatePayload
from src.errors import RandomRegexError
from random import choice


def depth_first_search_dependencies(
    item: FormItem,
    form_items: FormItems,
    form_items_metadata: FormMetadata,
    form_session: FormSession,
    visited_form_item_id: Set[FormID],
    data: UpdatePayload,
) -> Tuple[FormItems, FormItemMetadata]:
    visited_form_item_id.add(item.form_id)
    try:
        data[item.form_id] = _build_payload_value(
            item=item, metadata=form_items_metadata[item.form_id]
        )
    except RandomRegexError:
        return
    response = form_session.do_update(data=data, action=f"pre:notify:{item.form_id}")
    updated_form_items = FormItemParser.parse_form_items(response=response)
    updated_form_items_metadata = FormItemParser.parse_form_items_metdata(
        response=response
    )
    updated_form_items_triggering_change = {
        key: fi
        for key, fi in updated_form_items.items()
        if updated_form_items_metadata[key].triggers_change
    }
    dependent_form_items = get_new_values(
        form_items, updated_form_items_triggering_change
    )
    form_items.update(**updated_form_items)
    form_items_metadata.update(**updated_form_items_metadata)
    for key, dependant_item in dependent_form_items.items():
        if key not in visited_form_item_id:
            depth_first_search_dependencies(
                item=dependant_item,
                form_items=form_items,
                form_items_metadata=form_items_metadata,
                form_session=form_session,
                visited_form_item_id=visited_form_item_id,
                data=data,
            )


def _build_payload_value(item: FormItem, metadata: FormItemMetadata) -> str:
    if item.input_type == ItemType.CHECKBOX:
        return "on"
    elif item.input_type == ItemType.SELECT:
        choice(metadata.choices)
    elif item.input_type == ItemType.TEXT:
        if metadata.regex is not None:
            raise RandomRegexError()
        random_string = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Quisque tellus."
        )
        return random_string[metadata.min_length : metadata.max_length]


def get_new_values(old: dict, new: dict) -> dict:
    new_keys = set(new.keys()) - set(old.keys())
    return {key: new[key] for key in new_keys}
