import re
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

import click
import typer
from bs4 import BeautifulSoup
from requests import Session, Response

from src.dataclasses import Form
from src.errors import EmptyResultError
from src.parser import SearchResultParser
from src.types import FormItems, SearchResults


class FMSSession:
    CSRF_RE = re.compile(r"/ffw/content.do\?%24csrf=(?P<csrf>\w{24,25})$")

    def __init__(self):
        session = Session()
        session.get("https://www.formulare-bfinv.de/ffw/action/invoke.do?id=Welcome")
        self.session = session

    def select_form(self, search_term: str) -> Form:
        response = self.session.post(
            "https://www.formulare-bfinv.de/ffw/action/invoke.do?id=Welcome",
            data={"clientCaps": "moz;94.0;document.getElementById;frames"},
        )
        match = self.CSRF_RE.match(response.request.path_url)
        if match is None:
            sys.exit(1)
        csrf_token = match.groupdict()["csrf"]

        url = self._build_search_url(term=search_term, csrf=csrf_token)
        response = self.session.get(url=url)
        try:
            search_results = SearchResultParser.parse_search_results(response)
        except EmptyResultError:
            typer.echo(
                f"Keine Formulare mit dem Suchbegriff {repr(search_term)} gefunden",
                err=True,
            )
            raise typer.Exit(1)
        selected_form = self._get_user_selection(search_results)
        return selected_form

    def open_form(self, form: Form) -> Response:
        open_link = "https://www.formulare-bfinv.de/ffw/catalog/openForm.do"
        data = {
            "$requestType": "ajax",
            "path": f"catalog://{form.form_path}/{form.form_id}",
            "setCurrentFolder": "false",
        }
        response = self.session.post(open_link, data=data)
        redirect_url = response.json()["redirectTo"]
        response = self.session.get(f"https://www.formulare-bfinv.de/ffw{redirect_url}")
        return response

    def _get_user_selection(self, search_results: SearchResults) -> Form:
        self._display_selection_menu(search_results)
        choices = [str(order) for order in search_results.keys()]
        form_choice = click.Choice(choices=choices)
        selected_choice = typer.prompt(
            "Formular wählen",
            type=form_choice,
            default=choices[0],
            show_choices=False,
        )
        selected_form = search_results[int(selected_choice)]
        return selected_form

    @staticmethod
    def _display_selection_menu(results: SearchResults):
        for order, form in results.items():
            choice = click.style(f"{order}", bold=True, fg="blue")
            name = click.style(f"{str(form)}", bold=True)
            item = f"{choice}:\t{name}\n\tPfad: {form.form_path}"
            typer.echo(item, color=True)

    def _build_search_url(self, term: str, csrf: str):
        timestamp = datetime.now().timestamp
        return f"https://www.formulare-bfinv.de/ffw/search/globalSearch.do?_dc={timestamp}&lip_globalSearchType=forms&%24csrf={csrf}&lip_globalSearch={term}&%24requestType=ajax"


class FormSession:
    CONTEXT_RE = re.compile(r"/ffw/form/display.do\?%24context=(?P<context>\w{20})")

    def __init__(self, response: Response, fms_session: FMSSession):
        self.session = fms_session.session
        html = BeautifulSoup(response.content, features="html.parser")
        match = self.CONTEXT_RE.match(response.request.path_url)
        self.context = match.groupdict()["context"]
        find_hidden_input = partial(html.find, name="input", type="hidden")
        self.csrf = find_hidden_input(id="$csrf").attrs["value"]
        self.stage = int(find_hidden_input(id="$stage").attrs["value"])
        self.finalizer = find_hidden_input(id="$finalizer").attrs["value"]
        self.instanceIndex = find_hidden_input(id="$instanceIndex").attrs["value"]

    def do_update(self, data: dict = None, action: str = None) -> Response:
        url = "https://www.formulare-bfinv.de/ffw/form/update.do"
        data = data or {}
        action = (
            action
            if action is not None
            else f"/form/downloadXMLData.do?%24csrf={self.csrf}"
        )
        self.stage += 1
        form_data = {
            "$csrf": self.csrf,
            "$action": action,
            "$instanceIndex": self.instanceIndex,
            "$context": self.context,
            "$requestType": "ajax",
            "$finalizer": self.finalizer,
            "$stage": str(self.stage),
            "$viewSettings": '{"ffw.elementScrollbarPositions": {},"ffw.cocusControlId": ,"ffw.scrollTop": 1560}',
            **data,
        }
        return self.session.post(url=url, data=form_data)


class XMLFormSaver:
    FINISHED_FORM_FOLDER = Path("formulare")

    @classmethod
    def save_xml(cls, form: Form, form_items: FormItems):
        template = cls._xml_head(form)

        def custom_sort(key: str) -> int:
            if re.match(r"k\d+", key):
                return int(key[1:])
            return -1

        sorted_keys = sorted(list(form_items.keys()), key=custom_sort)
        for key in sorted_keys:
            item = form_items[key]
            line = f'<element id="{item.form_id}" /><!-- {item.form_number} {item.comment or ""} -->\n'
            template += "\t\t\t" + line
        template += cls._xml_foot()
        if not cls.FINISHED_FORM_FOLDER.exists():
            Path.mkdir(cls.FINISHED_FORM_FOLDER)
        finished_path = cls.FINISHED_FORM_FOLDER / f"{form.form_id}.xml"
        with open(finished_path, "w") as f:
            f.write(template)
        typer.secho(f"Entschlüsseltes Formular: {finished_path}", fg=typer.colors.GREEN)

    @staticmethod
    def _xml_head(form: Form) -> str:
        template = '<?xml version="1.0" encoding="UTF-8"?>\n'
        template += '<xml-data xmlns="http://www.lucom.com/ffw/xml-data-1.0.xsd">\n'
        template += f"\t<form>catalog://{form.form_path}/{form.form_id}</form>\n"
        template += "\t<instance>\n"
        template += "\t\t<datarow>\n"
        return template

    @staticmethod
    def _xml_foot() -> str:
        template = "\t\t</datarow>\n"
        template += "\t</instance>\n"
        template += "</xml-data>\n"
        return template
