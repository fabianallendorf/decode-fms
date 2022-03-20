import re
from typing import Optional, Any

from bs4 import BeautifulSoup, Tag
from requests import Response

from src.dataclasses import FormItem, FormItemMetadata, Form
from src.enums import ItemType, FormValueType
from src.errors import InvalidFormInputError, EmptyResultError
from src.types import FormItems, FormMetadata, SearchResults

FORM_SEGMENT_REGEX = re.compile(
    r"lip_segment-instance:Seite(?P<page>\d+):(?P<form_number>\w+)"
)


class FormItemParser:
    @classmethod
    def parse_form_items(cls, response: Response) -> FormItems:
        form_items: FormItems = {}
        json_response = response.json()
        html = BeautifulSoup(json_response["html"], features="html.parser")
        for tag in html.find_all("div", id=cls._is_segment):
            if match := FORM_SEGMENT_REGEX.match(tag.attrs["id"]):
                groups = match.groupdict()
                page = int(groups["page"])
                form_number = cls.parse_form_number(groups["form_number"])
                form_items.update(cls.parse_checkbox(tag, page, form_number))
                form_items.update(cls.parse_text_input(tag, page, form_number))
                form_items.update(cls.parse_text_area(tag, page, form_number))
        return form_items

    @classmethod
    def parse_form_items_metdata(cls, response: Response) -> FormMetadata:
        json_response = response.json()
        raw_metadata = json_response["controlAttribs"]
        select_choices = json_response["dataIncludes"]
        form_metadata: FormMetadata = {}
        for form_id, metadata in raw_metadata.items():
            try:
                metadata = cls._parse_form_item_metadata(raw_metadata[form_id])
            except InvalidFormInputError:
                continue
            form_metadata[form_id] = metadata
            if form_id in select_choices:
                form_metadata[form_id].choices = select_choices[form_id]
        return form_metadata

    @staticmethod
    def parse_form_number(form_number: str):
        if form_number.startswith("a"):
            form_number = form_number[1:].replace("_", ".")
        return form_number

    @staticmethod
    def parse_text_area(tag: Tag, page: int, form_number: str) -> FormItems:
        text_areas: FormItems = {}
        text_area_inputs = tag.find_all("textarea")
        for area in text_area_inputs:
            identifier = area.attrs["name"]
            text_areas[identifier] = FormItem(
                page=page,
                form_number=form_number,
                form_id=identifier,
                input_type=ItemType.TEXT,
            )
        return text_areas

    @classmethod
    def parse_text_input(cls, tag: Tag, page: int, form_number: str) -> FormItems:
        text_items: FormItems = {}
        text_item_tags = tag.find_all("input", type="text")
        for input in text_item_tags:
            input_type = cls._get_text_input_type(input=input)
            identifier = input.attrs["name"]
            text_items[identifier] = FormItem(
                page=page,
                form_number=form_number,
                form_id=identifier,
                input_type=input_type,
            )
        return text_items

    @staticmethod
    def parse_checkbox(parent: Tag, page: int, form_number: str) -> FormItems:
        checkboxes: FormItems = {}
        checkbox_inputs = parent.find_all("input", type="checkbox")
        yes_box = True
        for checkbox in checkbox_inputs:
            identifier = checkbox.attrs["name"]
            checkboxes[identifier] = FormItem(
                page=page,
                form_number=form_number,
                form_id=identifier,
                comment="Ja" if yes_box else "Nein",
                input_type=ItemType.CHECKBOX,
            )
            yes_box = not yes_box
        return checkboxes

    @staticmethod
    def _parse_form_item_metadata(raw_item_metadata: dict) -> FormItemMetadata:
        try:
            value_type = raw_item_metadata["type"]
        except KeyError:
            raise InvalidFormInputError
        value_type = FormValueType(value_type)

        def parse_value(key: str) -> Optional[Any]:
            try:
                return raw_item_metadata[key]
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

        return FormItemMetadata(
            value_type=value_type,
            mandatory=mandatory,
            triggers_change=triggers_change,
            checkbox_group=checkbox_group,
            min_length=min_length,
            max_length=max_length,
            regex=regex,
            date_format=date_format,
            choices=None,
        )

    @staticmethod
    def _is_segment(tag_id: str):
        return tag_id is not None and FORM_SEGMENT_REGEX.match(tag_id)

    @staticmethod
    def _get_text_input_type(input: Tag) -> ItemType:
        tag_siblings = [s for s in input.next_siblings if isinstance(s, Tag)]
        input_type = ItemType.TEXT
        if len(tag_siblings) > 0:
            sibling = tag_siblings[0]
            input_type = (
                ItemType.SELECT
                if sibling.name == "a" and sibling.attrs["id"].startswith("opener")
                else ItemType.TEXT
            )
        return input_type


class SearchResultParser:
    @classmethod
    def parse_search_results(cls, response: Response) -> SearchResults:
        raw_search_results = response.json()
        search_results: SearchResults = {}
        if "results" not in raw_search_results:
            raise EmptyResultError()
        clickable_raw_results = [
            r for r in raw_search_results["results"] if r.get("clickable", False)
        ]
        for index, raw_result in enumerate(clickable_raw_results):
            search_result = cls._parse_search_result(raw_result)
            search_results[index + 1] = search_result
        return search_results

    @staticmethod
    def _parse_search_result(entry: dict) -> Form:
        display_name = entry["title"]
        form_id = entry["formId"]
        path = entry["catalogPath"]
        return Form(display_name=display_name, form_id=form_id, form_path=path)
