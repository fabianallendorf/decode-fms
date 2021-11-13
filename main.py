import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from bs4.element import Tag
import requests
from dataclasses import dataclass
from enum import Enum
import sys
from datetime import datetime
from requests.sessions import Session
import typer
import click
from pathlib import Path

FORM_SEGMENT_REGEX = re.compile(
    r"lip_segment-instance:Seite(?P<page>\d+):(?P<form_number>\w+)"
)
CSRF_RE = re.compile(r"/ffw/content.do\?%24csrf=(?P<csrf>\w{24,25})$")
CONTEXT_RE = re.compile(r"/ffw/form/display.do\?%24context=(?P<context>\w{20})")

FINISHED_FORM_FOLDER = Path("formulare")
if not FINISHED_FORM_FOLDER.exists():
    Path.mkdir(FINISHED_FORM_FOLDER)


class InputType:
    CHECKBOX = "checkbox"
    TEXT = "text"
    SELECT = "select"


class FormValueType(Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"


@dataclass
class FormInput:
    page: int
    form_number: str
    form_id: str
    input_type: InputType
    comment: Optional[str] = None


@dataclass
class FormInputMeta:
    value_type: FormValueType
    mandatory: bool
    triggers_change: bool
    checkbox_group: Optional[str]
    min_length: Optional[int]
    max_length: Optional[int]
    regex: Optional[str]
    date_format: Optional[str]


@dataclass
class SearchResult:
    form_id: str
    form_path: str
    display_name: str
    result_order: int

    def __str__(self) -> str:
        return self.display_name


class EmptyResultError(Exception):
    pass


def initiate_session() -> requests.Session:
    session = requests.Session()
    session.get("https://www.formulare-bfinv.de/ffw/action/invoke.do?id=Welcome")
    return session


def select_form(search_term: str, session: Session) -> SearchResult:
    response = session.post(
        "https://www.formulare-bfinv.de/ffw/action/invoke.do?id=Welcome",
        data={"clientCaps": "moz;94.0;document.getElementById;frames"},
    )
    match = CSRF_RE.match(response.request.path_url)
    if match is None:
        sys.exit(1)
    csrf_token = match.groupdict()["csrf"]

    url = _search_url(term=search_term, csrf=csrf_token)
    response = session.get(url=url)
    raw_serach_results = response.json()
    try:
        search_results = parse_search_results(raw_serach_results)
    except EmptyResultError:
        typer.echo(
            f"Keine Formulare mit dem Suchbegriff {repr(search_term)} gefunden",
            err=True,
        )
        raise typer.Exit(1)
    display_selection_menu(search_results)
    choices = [str(s.result_order) for s in search_results]
    form_choice = click.Choice(choices=choices)
    selected_choice = typer.prompt(
        "Formular wählen",
        type=form_choice,
        default=choices[0],
        show_choices=False,
    )
    selected_result = [
        r for r in search_results if r.result_order == int(selected_choice)
    ][0]
    return selected_result


def _search_url(term: str, csrf: str):
    timestamp = datetime.now().timestamp
    return f"https://www.formulare-bfinv.de/ffw/search/globalSearch.do?_dc={timestamp}&lip_globalSearchType=forms&%24csrf={csrf}&lip_globalSearch={term}&%24requestType=ajax"


def parse_search_results(raw_search_results: dict) -> List[SearchResult]:
    search_results: List[SearchResult] = []
    if "results" not in raw_search_results:
        raise EmptyResultError()
    clickable_raw_results = [
        r for r in raw_search_results["results"] if r.get("clickable", False)
    ]
    for index, raw_result in enumerate(clickable_raw_results):
        search_result = _parse_valid_search_result(raw_result["value"], index + 1)
        search_results.append(search_result)
    return search_results


def display_selection_menu(results: List[SearchResult]):
    for result in results:
        choice = click.style(f"{result.result_order}", bold=True, fg="blue")
        name = click.style(f"{str(result)}", bold=True)
        item = f"{choice}:\t{name}\n\tPfad: {result.form_path}"
        typer.echo(item, color=True)


def _parse_valid_search_result(html_value: str, order: int) -> SearchResult:
    html = BeautifulSoup(html_value, features="html.parser")
    display_name = html.find("div", class_="title").text
    subtitles = html.find_all("div", class_="subtitle")
    form_id_span = subtitles[0]
    form_id = form_id_span.find("span").contents[1].text
    path_span = subtitles[1]
    path = path_span.find("span").contents[1].text
    return SearchResult(
        display_name=display_name, form_id=form_id, form_path=path, result_order=order
    )


def open_form(search_result: SearchResult, session: Session) -> requests.Response:
    open_link = "https://www.formulare-bfinv.de/ffw/catalog/openForm.do"
    data = {
        "$requestType": "ajax",
        "path": f"catalog://{search_result.form_path}/{search_result.form_id}",
        "setCurrentFolder": "false",
    }
    response = session.post(open_link, data=data)
    redirect_url = response.json()["redirectTo"]
    response = session.get(f"https://www.formulare-bfinv.de/ffw{redirect_url}")
    return response


def run(search_term: str = typer.Option(..., "--search", prompt="Formulare suchen")):
    session = initiate_session()
    selected_result: SearchResult = select_form(search_term, session=session)
    response = open_form(search_result=selected_result, session=session)
    match = CONTEXT_RE.match(response.request.path_url)
    context = match.groupdict()["context"]
    soup = BeautifulSoup(response.content, features="html.parser")
    csrf = soup.find("input", type="hidden", id="$csrf").attrs["value"]
    stage = int(soup.find("input", type="hidden", id="$stage").attrs["value"])
    finalizer = soup.find("input", type="hidden", id="$finalizer").attrs["value"]
    instanceIndex = soup.find("input", type="hidden", id="$instanceIndex").attrs[
        "value"
    ]
    action = f"/form/downloadXMLData.do?%24csrf={csrf}"
    form_items = parse_form_items(soup)
    update_kwargs = dict(
        session=session,
        csrf=csrf,
        action=action,
        context=context,
        stage=stage,
        finalizer=finalizer,
        instanceIndex=instanceIndex,
    )
    response_json = do_update(data={}, **update_kwargs)
    form_metadata = _parse_form_metadata(
        response_json["controlAttribs"], parsed_form_ids=form_items.keys()
    )
    items_triggering_updates = set(
        key
        for key, meta in form_metadata.items()
        if meta.triggers_change and meta.value_type == FormValueType.BOOLEAN
    )
    visited_key = set()
    total = 100
    with typer.progressbar(
        length=total, label=f"Formular {selected_result.form_id} entschlüsseln"
    ) as progress:
        while len(items_triggering_updates) > 0:
            key = items_triggering_updates.pop()
            update_kwargs["stage"] += 1
            response_json = do_update(data={key: "on"}, **update_kwargs)
            soup = BeautifulSoup(response_json["html"], features="html.parser")
            new_form_items = parse_form_items(soup)
            form_items.update(**new_form_items)
            new_form_metadata = _parse_form_metadata(
                response_json["controlAttribs"], form_items.keys()
            )
            form_metadata.update(**new_form_metadata)
            visited_key.add(key)
            new_items_triggering_updates = set(
                k
                for k, meta in form_metadata.items()
                if meta.triggers_change
                and meta.value_type == FormValueType.BOOLEAN
                and k not in visited_key
            )
            items_triggering_updates |= new_items_triggering_updates
            if len(items_triggering_updates) > 0:
                progress.update(len(visited_key) / len(items_triggering_updates))
    save_xml(form=selected_result, form_items=form_items)


def _parse_form_metadata(
    raw_metadata: dict, parsed_form_ids: List[int]
) -> Dict[int, FormInputMeta]:
    form_metadata: Dict[int, FormInputMeta] = {}
    for form_id in parsed_form_ids:
        if form_id not in raw_metadata:
            continue
        metadata = _parse_control_metadata(raw_metadata[form_id])
        form_metadata[form_id] = metadata
    return form_metadata


def _parse_control_metadata(metadata: dict) -> FormInputMeta:
    value_type = FormValueType(metadata["type"])

    def parse_value(key: str) -> Optional[Any]:
        try:
            return metadata[key]
        except KeyError:
            return None

    def parse_bool(key: str) -> bool:
        return parse_value(key) is True

    def parse_integer(key: str) -> Optional[int]:
        try:
            return int(parse_value(key))
        except TypeError:
            return None

    mandatory = parse_bool("mandatory")
    triggers_change = parse_bool("notifyOnChange")
    checkbox_group = parse_value("checkGroup")
    min_length = parse_integer("minLength")
    max_length = parse_integer("maxLength")
    regex = parse_value("regExp")
    date_format = parse_value("mask")

    return FormInputMeta(
        value_type=value_type,
        mandatory=mandatory,
        triggers_change=triggers_change,
        checkbox_group=checkbox_group,
        min_length=min_length,
        max_length=max_length,
        regex=regex,
        date_format=date_format,
    )


def is_segment(tag_id: str):
    return tag_id is not None and FORM_SEGMENT_REGEX.match(tag_id)


def parse_form_items(soup):
    form_items = {}

    for tag in soup.find_all("div", id=is_segment):
        if match := FORM_SEGMENT_REGEX.match(tag.attrs["id"]):
            groups = match.groupdict()
            page = groups["page"]
            form_number = parse_form_number(groups["form_number"])
            form_items.update(parse_checkbox(tag, page, form_number))
            form_items.update(parse_text_input(tag, page, form_number))
            form_items.update(parse_text_area(tag, page, form_number))
    return form_items


def get_mandatory_fields(soup):
    mandatory_form_ids = {}
    for tag in soup.find_all(is_mandatory_input):
        mandatory_form_ids[tag.attrs["name"]] = ""
    return mandatory_form_ids


def is_mandatory_input(tag):
    return (
        "class" in tag.attrs
        and "ffw_mandatory" in tag.attrs["class"]
        and "formControl" in tag.attrs["class"]
        and "formControlCheckbox" not in tag.attrs["class"]
    )


def parse_form_number(form_number):
    if form_number.startswith("a"):
        form_number = form_number[1:].replace("_", ".")
    return form_number


def parse_text_area(tag, page, form_number) -> Dict[str, FormInput]:
    text_areas: Dict[str, FormInput] = {}
    text_area_inputs = tag.find_all("textarea")
    for area in text_area_inputs:
        identifier = area.attrs["name"]
        text_areas[identifier] = FormInput(
            page=page,
            form_number=form_number,
            form_id=identifier,
            input_type=InputType.TEXT,
        )
    return text_areas


def parse_text_input(tag, page, form_number) -> Dict[str, FormInput]:
    text_inputs: Dict[str, FormInput] = {}
    text_inputs_tags = tag.find_all("input", type="text")
    for input in text_inputs_tags:
        tag_siblings = [s for s in input.next_siblings if isinstance(s, Tag)]
        if len(tag_siblings) == 0:
            continue
        sibling = tag_siblings[0]
        input_type = (
            InputType.SELECT
            if sibling.name == "a" and sibling.attrs["id"].startswith("opener")
            else InputType.TEXT
        )
        identifier = input.attrs["name"]
        text_inputs[identifier] = FormInput(
            page=page,
            form_number=form_number,
            form_id=identifier,
            input_type=input_type,
        )
    return text_inputs


def parse_checkbox(parent, page, form_number) -> Dict[str, FormInput]:
    checkboxes: Dict[str, FormInput] = {}
    checkbox_inputs = parent.find_all("input", type="checkbox")
    yes_box = True
    for checkbox in checkbox_inputs:
        identifier = checkbox.attrs["name"]
        checkboxes[identifier] = FormInput(
            page=page,
            form_number=form_number,
            form_id=identifier,
            comment="Ja" if yes_box else "Nein",
            input_type=InputType.CHECKBOX,
        )
        yes_box = not yes_box
    return checkboxes


def do_update(
    data: dict,
    session: requests.Session,
    csrf: str,
    action: str,
    context: str,
    stage: int,
    instanceIndex: str = "-1",
    finalizer: str = "1",
) -> dict:
    url = "https://www.formulare-bfinv.de/ffw/form/update.do"
    form_data = {
        "$csrf": csrf,
        "$action": action,
        "$instanceIndex": instanceIndex,
        "$context": context,
        "$requestType": "ajax",
        "$finalizer": finalizer,
        "$stage": str(stage),
        "$viewSettings": '{"ffw.elementScrollbarPositions": {},"ffw.cocusControlId": ,"ffw.scrollTop": 1560}',
        **data,
    }
    response = session.post(url=url, data=form_data)
    return response.json()


def save_xml(form: SearchResult, form_items: Dict[str, FormInput]):
    template = _xml_head(form)

    def custom_sort(key: str) -> int:
        if re.match(r"k\d+", key):
            return int(key[1:])
        return -1

    sorted_keys = sorted(list(form_items.keys()), key=custom_sort)
    for key in sorted_keys:
        item = form_items[key]
        line = f'<element id="{item.form_id}" /><!-- {item.form_number} {item.comment or ""} -->\n'
        template += "\t\t\t" + line
    template += _xml_foot()
    with open(FINISHED_FORM_FOLDER / f"{form.form_id}.xml", "w") as f:
        f.write(template)


def _xml_head(form: SearchResult) -> str:
    template = '<?xml version="1.0" encoding="UTF-8"?>\n'
    template += '<xml-data xmlns="http://www.lucom.com/ffw/xml-data-1.0.xsd">\n'
    template += f"\t<form>catalog://{form.form_path}/{form.form_id}</form>\n"
    template += "\t<instance>\n"
    template += "\t\t<datarow>\n"
    return template


def _xml_foot() -> str:
    template = "\t\t</datarow>\n"
    template += "\t</instance>\n"
    template += "</xml-data>\n"
    return template


if __name__ == "__main__":
    typer.run(run)
