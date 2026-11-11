"""Tests for the HTMX upload form on /import and the inline results it receives."""

import io
from html.parser import HTMLParser

CSV = "Date,Description,Amount\n2024-01-01,Test Transaction,-10.50\n"
# Both result blocks offer a button that empties the swap target so the form can be reused.
CLEAR_RESULTS = "document.getElementById('uploadResults').innerHTML = ''"


class _Page(HTMLParser):
    """Collects elements by id, the text of each ``<p>`` and ``<button>``, and inline scripts."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str | None]] = {}
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.paragraphs: list[str] = []
        self.buttons: list[tuple[str, str | None]] = []  # (label, onclick)
        self.scripts: list[str] = []
        self._open: str | None = None
        self._attrs: dict[str, str | None] = {}
        self._text: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if "id" in attributes:
            self.by_id[attributes["id"]] = {"tag": tag, **attributes}
        if tag in ("p", "button", "script"):
            self._open, self._attrs, self._text = tag, attributes, []

    def handle_data(self, data):
        if self._open:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag != self._open:
            return
        text = "".join(self._text).strip()
        if tag == "p":
            self.paragraphs.append(text)
        elif tag == "button":
            self.buttons.append((text, self._attrs.get("onclick")))
        elif "src" not in self._attrs:
            self.scripts.append(text)
        self._open = None

    def with_class(self, name: str) -> list[dict[str, str | None]]:
        return [attrs for _, attrs in self.tags if name in (attrs.get("class") or "").split()]

    def links(self) -> list[str | None]:
        return [attrs.get("href") for tag, attrs in self.tags if tag == "a"]


def _upload(client, name: str, content: bytes) -> _Page:
    response = client.post("/api/upload/csv-htmx", files={"file": (name, io.BytesIO(content), "text/csv")})
    assert response.status_code == 200  # HTMX only swaps 2xx responses, so errors are 200 with an error block
    assert "text/html" in response.headers["content-type"]
    return _Page(response.text)


class TestUploadResults:
    def test_success_reports_counts_and_links_to_review(self, test_client):
        page = _upload(test_client, "test.csv", CSV.encode())

        assert len(page.with_class("alert-success")) == 1
        assert not page.with_class("alert-error")
        assert "File: test.csv" in page.paragraphs
        assert "Rows processed: 1" in page.paragraphs
        assert "New transactions: 1" in page.paragraphs
        assert "Duplicates skipped: 0" in page.paragraphs
        assert "/review" in page.links()
        assert page.buttons == [("Upload Another File", CLEAR_RESULTS)]

    def test_reuploading_the_same_file_counts_duplicates_not_new_rows(self, test_client):
        _upload(test_client, "test.csv", CSV.encode())

        page = _upload(test_client, "test.csv", CSV.encode())

        assert "New transactions: 0" in page.paragraphs
        assert "Duplicates skipped: 1" in page.paragraphs

    def test_non_csv_upload_returns_an_error_block(self, test_client):
        page = _upload(test_client, "test.txt", b"invalid content")

        assert len(page.with_class("alert-error")) == 1
        assert not page.with_class("alert-success")
        assert "Only CSV files are allowed" in page.paragraphs
        assert page.buttons == [("Try Again", CLEAR_RESULTS)]


class TestImportPageForm:
    def test_form_posts_to_the_htmx_endpoint_and_targets_existing_elements(self, test_client):
        response = test_client.get("/import")
        assert response.status_code == 200
        page = _Page(response.text)

        form = page.by_id["uploadForm"]
        assert form["tag"] == "form"
        assert form["hx-post"] == "/api/upload/csv-htmx"
        assert form["hx-encoding"] == "multipart/form-data"
        # The swap target and progress indicator the form names must exist on the page.
        assert form["hx-target"] == "#uploadResults"
        assert form["hx-indicator"] == "#uploadProgress"
        assert page.by_id["uploadResults"]["tag"] == "div"
        assert "htmx-indicator" in (page.by_id["uploadProgress"]["class"] or "").split()

    def test_file_input_feeds_the_endpoint_and_submit_starts_disabled(self, test_client):
        page = _Page(test_client.get("/import").text)

        file_input = page.by_id["fileInput"]
        assert file_input["type"] == "file"
        assert file_input["name"] == "file"  # the endpoint reads the `file` form field
        assert file_input["accept"] == ".csv"
        # No file chosen yet, so submitting must not be possible.
        assert "disabled" in page.by_id["uploadButton"]

    def test_inline_script_enables_the_button_on_file_choice_and_resets_the_form_after_success(self, test_client):
        page = _Page(test_client.get("/import").text)
        script = "\n".join(page.scripts)

        # The file input calls a handler; the page must define it and the handler must flip the button.
        handler = (page.by_id["fileInput"]["onchange"] or "").removesuffix("()")
        assert handler == "updateUploadButton"
        assert f"function {handler}(" in script
        assert "uploadButton.disabled = false" in script
        # After a successful upload of this form, the form is reset.
        assert "htmx:afterRequest" in script
        assert "getElementById('uploadForm').reset()" in script
