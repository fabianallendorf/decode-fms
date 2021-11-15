import typer
from src.algorithms import depth_first_search_dependencies

from src.dataclasses import Form
from src.parser import FormItemParser
from src.services import FMSSession, FormSession, XMLFormSaver


def run(search_term: str = typer.Option(..., "--search", prompt="Formulare suchen")):
    session = FMSSession()
    form: Form = session.select_form(search_term)
    response = session.open_form(form=form)
    form_session = FormSession(response=response, fms_session=session)
    response = form_session.do_update()
    form_items = FormItemParser.parse_form_items(response=response)
    form_items_metadata = FormItemParser.parse_form_items_metdata(response=response)
    items_triggering_updates = [
        item
        for key, item in form_items.items()
        if form_items_metadata[key].triggers_change
    ]
    visited_form_item_id = set()
    with typer.progressbar(items_triggering_updates) as progress:
        for item in progress:
            depth_first_search_dependencies(
                item=item,
                form_items=form_items,
                form_items_metadata=form_items_metadata,
                form_session=form_session,
                visited_form_item_id=visited_form_item_id,
                data={},
            )
    XMLFormSaver.save_xml(form, form_items=form_items)


if __name__ == "__main__":
    typer.run(run)
