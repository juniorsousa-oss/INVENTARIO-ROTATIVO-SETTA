"""Regression checks for the inventory presentation, without app side effects."""
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import setta_shell


class InventoryShellTests(TestCase):
    def test_render_drawer_states(self):
        st = Mock()
        for opened, state in ((False, "closed"), (True, "open")):
            setta_shell.render_shell(st, opened)
            markup = st.html.call_args.args[0]
            self.assertIn(f"setta-shell-marker setta-drawer-{state}", markup)
            self.assertIn("data:font/woff2;base64,", markup)
            self.assertIn("--inv-top:58px", markup)
            self.assertIn("--inv-nav:220px", markup)

    def test_stylesheet_refreshes_in_same_process(self):
        st = Mock()
        with TemporaryDirectory() as directory:
            css = Path(directory) / "setta-inventory.css"
            with patch.object(setta_shell, "_ASSETS", css.parent), patch.object(
                setta_shell, "_encoded", return_value="AAAA"
            ):
                css.write_text(":root{--release:old}", encoding="utf-8")
                setta_shell.render_shell(st, False)
                self.assertIn("--release:old", st.html.call_args.args[0])
                css.write_text(":root{--release:new}", encoding="utf-8")
                setta_shell.render_shell(st, True)
                self.assertIn("--release:new", st.html.call_args.args[0])
                self.assertNotIn("--release:old", st.html.call_args.args[0])

    def test_official_logo_has_not_been_transformed(self):
        st = Mock()
        setta_shell.render_top(st)
        markup = st.html.call_args.args[0]
        logo = Path(__file__).resolve().parents[1] / "assets" / "setta-logo-oficial.svg"
        expected = base64.b64encode(logo.read_bytes()).decode("ascii")
        self.assertIn(expected, markup)
        self.assertIn('alt="Setta"', markup)

    def test_routes_keep_unique_titles_and_breadcrumbs(self):
        st = Mock()
        titles = set()
        for page in setta_shell._ROUTES:
            title = setta_shell.route_title(page)
            self.assertNotIn(title, titles)
            titles.add(title)
            setta_shell.render_page(st, page)
            markup = st.html.call_args.args[0]
            self.assertIn("setta-inv-breadcrumb", markup)
            self.assertIn(f"<h1>{title}</h1>", markup)
        self.assertEqual(len(titles), 7)

    def test_sidebar_routes_have_distinct_material_icons(self):
        icons = [setta_shell.route_icon(page) for page in setta_shell._ROUTES]
        self.assertEqual(len(set(icons)), 7)
        self.assertTrue(all(icon.startswith(":material/") and icon.endswith(":") for icon in icons))

    def test_status_markup_never_interprets_status_as_html(self):
        self.assertIn("inv-status-count", setta_shell.status_badge("EM CONTAGEM"))
        self.assertIn("inv-status-closed", setta_shell.status_badge("FECHADO"))
        self.assertIn("&lt;script&gt;", setta_shell.status_badge("<script>"))
