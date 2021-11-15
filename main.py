import re
from typing import Dict
import typer
from random import choice

from src.dataclasses import FormItem, FormItemMetadata, Form
from src.enums import ItemType
from src.errors import RandomRegexError
from src.parser import FormItemParser
from src.services import FMSSession, FormSession, XMLFormSaver

FORM_SEGMENT_REGEX = re.compile(
    r"lip_segment-instance:Seite(?P<page>\d+):(?P<form_number>\w+)"
)
CSRF_RE = re.compile(r"/ffw/content.do\?%24csrf=(?P<csrf>\w{24,25})$")
CONTEXT_RE = re.compile(r"/ffw/form/display.do\?%24context=(?P<context>\w{20})")


def run(search_term: str = typer.Option(..., "--search", prompt="Formulare suchen")):
    session = FMSSession()
    form: Form = session.select_form(search_term)
    response = session.open_form(form=form)
    form_session = FormSession(response=response, fms_session=session)
    response = form_session.do_update()
    form_items = FormItemParser.parse_form_items(response=response)
    form_items_metadata = FormItemParser.parse_form_item_metdata(response=response)
    select_choices = response.json()["dataIncludes"]
    items_triggering_updates = [
        key for key, meta in form_items_metadata.items() if meta.triggers_change
    ]
    items_triggering_updates.reverse()
    visited_key = set()
    while len(items_triggering_updates) > 0:
        key = items_triggering_updates.pop()
        item = form_items[key]
        try:
            value = _build_value(
                item, metadata=form_items_metadata, choices=select_choices
            )
        except RandomRegexError:
            typer.echo(
                f"Für das Element {repr(key)} kann momentan kein zufälliger Wert generiert werden."
            )
            continue
        response = form_session.do_update(data={key: value}, action=f"pre:notify:{key}")
        select_choices.update(response.json()["dataIncludes"])
        new_form_items = FormItemParser.parse_form_items(response=response)
        form_items.update(**new_form_items)
        new_form_metadata = FormItemParser.parse_form_item_metdata(response=response)
        form_items_metadata.update(**new_form_metadata)
        visited_key.add(key)
        new_items_triggering_updates = [
            new_key
            for new_key, meta in new_form_metadata.items()
            if meta.triggers_change
            and new_key not in visited_key
            and new_key not in items_triggering_updates
        ]
        new_items_triggering_updates.reverse()
        items_triggering_updates += new_items_triggering_updates
        total = len(visited_key) + len(items_triggering_updates)
        fraction_done = len(visited_key) / total
        typer.secho(
            f"Formular entschlüsselt: {fraction_done:.2%}\r",
            nl=False,
            fg=typer.colors.BLUE,
        )
    XMLFormSaver.save_xml(form, form_items=form_items)


def _build_value(
    item: FormItem, metadata: Dict[str, FormItemMetadata], choices: Dict[str, str]
) -> str:
    if item.input_type == ItemType.CHECKBOX:
        return "on"
    elif item.input_type == ItemType.SELECT:
        choice(choices[item.form_id])
    elif item.input_type == ItemType.TEXT:
        item_metadata = metadata[item.form_id]
        if item_metadata.regex is not None:
            raise RandomRegexError()
        random_string = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Quisque tellus."
        )
        return random_string[item_metadata.min_length : item_metadata.max_length]


if __name__ == "__main__":
    typer.run(run)
