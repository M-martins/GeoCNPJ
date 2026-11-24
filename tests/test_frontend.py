import unittest
from pathlib import Path


class FrontendTests(unittest.TestCase):
    @staticmethod
    def page_bundle(name):
        root = Path(__file__).parent.parent / "frontend"
        return ((root / f"{name}.html").read_text(encoding="utf-8") +
                (root / "assets" / f"{name}.js").read_text(encoding="utf-8"))

    def test_global_shell_tabs_and_shared_ui_are_available(self):
        root = Path(__file__).parent.parent / "frontend"
        ui = (root / "assets" / "ui.js").read_text(encoding="utf-8")
        css = (root / "assets" / "app.css").read_text(encoding="utf-8")
        collection = (root / "collection.html").read_text(encoding="utf-8")
        projects = (root / "projects.html").read_text(encoding="utf-8")
        for marker in ("global-shell", "shellProject", "GeoUI", "ui-modal", "ui-toast"):
            self.assertIn(marker, ui + css)
        self.assertIn("'/etapas'", ui)
        self.assertIn("'Etapas'", ui)
        self.assertNotIn("'Pipeline'", ui)
        for tab in ("overview", "official", "bases", "results", "operations"):
            self.assertIn(f'data-tab="{tab}"', collection)
        self.assertIn('/assets/projects.js', projects)
        for page in ("projects.html", "collection.html", "index.html", "map.html"):
            content = (root / page).read_text(encoding="utf-8")
            self.assertIn('/assets/app.css', content)
            self.assertIn('/assets/ui.js', content)

    def test_municipality_help_explains_where_uf_comes_from(self):
        page = (Path(__file__).parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("traz código e nome, mas não informa a UF", page)
        self.assertIn("lista complementar de código e UF publicada pela Receita", page)
        self.assertIn("lista complementar de código e UF", page)

    def test_collection_shows_deduplicated_storage_overview(self):
        page = self.page_bundle("collection")
        for marker in ('id="storageSummary"', '/api/collection/dashboard', 'OCUPAÇÃO FÍSICA GERENCIADA',
                       'ARTEFATOS COMPARTILHADOS', 'id="projectStorage"', 'logical_size',
                       "const units=['B','KB','MB','GB','TB']"):
            self.assertIn(marker, page)
        self.assertNotIn("unitDisplay:'short'", page)
        for marker in ('id="recoveries"', '/api/recovery', 'function renderRecovery', 'Examinar'):
            self.assertIn(marker, page)
        for marker in ('id="integrity"', '/api/integrity', 'function renderIntegrity', 'Enviar à Lixeira',
                       'function linkOrphan', 'Vincular ao projeto'):
            self.assertIn(marker, page)

    def test_review_map_has_search_selection_and_exports(self):
        page = self.page_bundle("map")
        for marker in ('id="neighborhood"', 'id="selectPage"', "exportRows('csv')", "exportRows('geojson')"):
            self.assertIn(marker, page)
        self.assertIn("selectedRows.size", page)
        self.assertIn("/map/export", page)

    def test_searches_are_separate_and_approximate(self):
        page = self.page_bundle("map")
        for marker in ('id="searchCnpj"', 'id="searchName"', 'id="searchStreet"', 'id="searchNumber"',
                       "/map/suggestions", "updateSuggestions"):
            self.assertIn(marker, page)
        self.assertIn("$('neighborhood').value=p.bairro", page)
        self.assertIn('id="clearFilters"', page)
        self.assertIn("function clearAllFilters", page)
        self.assertIn("map.fitBounds", page)

    def test_overlapping_points_use_spiderfy(self):
        page = self.page_bundle("map")
        for marker in ("function spiderfy", "coordinateKey", "spider-lines", "spider-point", "group.slice(offset,offset+36)"):
            self.assertIn(marker, page)

    def test_street_search_keeps_numeric_forms_distinct_and_rejects_weak_matches(self):
        root = Path(__file__).parent.parent
        backend = (root / "backend" / "map_index.py").read_text(encoding="utf-8")
        self.assertNotIn("NUMBER_ALIASES", backend)
        self.assertIn('for term in normalized(filters["street"]).split()', backend)
        self.assertIn('n_street LIKE ?', backend)
        self.assertIn('n_number LIKE ?', backend)
        page = self.page_bundle("map")
        self.assertIn("focusFeatures", page)
        self.assertIn("applyFilters({focus:true})", page)

    def test_pages_have_external_assets_and_accessible_shared_states(self):
        root = Path(__file__).parent.parent / "frontend"
        for name in ("projects", "collection", "index", "map"):
            html = (root / f"{name}.html").read_text(encoding="utf-8")
            self.assertNotIn("<style>", html)
            self.assertIn(f'/assets/{name}.css', html)
            self.assertTrue((root / "assets" / f"{name}.css").exists())
            if name != "projects":
                self.assertNotIn("<script>", html)
                self.assertIn(f'/assets/{name}.js', html)
                self.assertTrue((root / "assets" / f"{name}.js").exists())
            self.assertIn(f'<script defer src="/assets/{name}.js', html)
        ui = (root / "assets" / "ui.js").read_text(encoding="utf-8")
        css = (root / "assets" / "app.css").read_text(encoding="utf-8")
        for marker in ("function busy", "function state", "async function request", "aria-busy", "e.key==='Escape'"):
            self.assertIn(marker, ui)
        for marker in (":focus-visible", ":disabled", "prefers-reduced-motion", ".ui-state", ".ui-spinner"):
            self.assertIn(marker, css)
        collection = (root / "assets" / "collection.js").read_text(encoding="utf-8")
        map_js = (root / "assets" / "map.js").read_text(encoding="utf-8")
        self.assertIn("ArrowRight", collection)
        self.assertIn("aria-selected", collection)
        self.assertIn('role="button" tabindex="0"', map_js)
        self.assertIn('role="button" tabindex="0"', map_js)

    def test_map_loads_viewport_and_page_instead_of_full_geojson(self):
        page = self.page_bundle("map")
        self.assertIn("/map/viewport", page)
        self.assertIn("/map/records", page)
        self.assertIn("AbortController", page)
        self.assertNotIn("/map-data`,", page)

    def test_map_exposes_cnae_filters_and_loads_full_details_on_demand(self):
        page = self.page_bundle("map")
        html = (Path(__file__).parent.parent / "frontend" / "map.html").read_text(encoding="utf-8")
        for marker in ('id="searchCnae"', 'id="searchActivity"', 'id="suggestActivity"',
                       "/map/records/${encodeURIComponent(cnpj)}", "CNAE principal",
                       "CNAEs secundários", "data_inicio_atividade"):
            self.assertIn(marker, page)
        for marker in ("cnae_secao_codigo", "cnae_divisao_codigo", "cnae_grupo_codigo", "/assets/cnae.css"):
            self.assertIn(marker, page)
        for element_id in ("searchCnpj","searchName","searchStreet","searchActivity",
                           "suggestCnpj","suggestName","suggestStreet","suggestActivity"):
            self.assertEqual(html.count(f'id="{element_id}"'),1)
        self.assertIn("if(!input){console.warn", page)
        self.assertIn("m.quality?.review", page)

    def test_operations_are_kept_inside_collection(self):
        root = Path(__file__).parent.parent
        ui = (root / "frontend" / "assets" / "ui.js").read_text(encoding="utf-8")
        collection = (root / "frontend" / "assets" / "collection.js").read_text(encoding="utf-8")
        backend = (root / "backend" / "api" / "pages.py").read_text(encoding="utf-8")
        self.assertNotIn("['/operations','Operações']", ui)
        self.assertNotIn("location.pathname==='/operations'", collection)
        self.assertIn("'/collection#'+name", collection)
        self.assertIn('RedirectResponse("/collection#operations"', backend)

    def test_contextual_explanations_are_available(self):
        root = Path(__file__).parent.parent
        index = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        map_html = (root / "frontend" / "map.html").read_text(encoding="utf-8")
        guidance = (root / "frontend" / "assets" / "guidance.js").read_text(encoding="utf-8")
        ui = (root / "frontend" / "assets" / "ui.js").read_text(encoding="utf-8")
        pages = (root / "backend" / "api" / "pages.py").read_text(encoding="utf-8")
        self.assertIn('/assets/guidance.css', index)
        self.assertIn('/assets/guidance.js', index)
        self.assertIn('id="mapHelp"', map_html)
        self.assertIn('id="mapHelpToggle"', map_html)
        self.assertIn('https://github.com/ipea/geocodebr', map_html)
        self.assertIn('https://github.com/ipea/geocodebr', index)
        self.assertNotIn('id="refreshGeo"', index)
        self.assertLess(index.index('id="geoHistory"'), index.index('id="geoReadiness"'))
        for marker in ("Dados oficiais", "Recorte municipal enriquecido", "Score", "Pontos coincidentes"):
            self.assertIn(marker, guidance)
        self.assertNotIn("['/metodologia','Ajuda']", ui)
        self.assertIn('"/metodologia"', pages)
        methodology = (root / 'frontend' / 'metodologia.html').read_text(encoding='utf-8')
        for marker in ('geocodebr', 'CNEFE', 'score', 'desvio_metros', 'Alta confiança'):
            self.assertIn(marker, methodology)
        self.assertIn('href="/metodologia"', map_html)
        self.assertIn('href="/metodologia"', index)

    def test_home_explains_project_phases_and_technology(self):
        root = Path(__file__).parent.parent
        home = (root / "frontend" / "home.html").read_text(encoding="utf-8")
        css = (root / "frontend" / "assets" / "home.css").read_text(encoding="utf-8")
        pages = (root / "backend" / "api" / "pages.py").read_text(encoding="utf-8")
        ui = (root / "frontend" / "assets" / "ui.js").read_text(encoding="utf-8")
        for marker in ("Receita Federal", "Dados oficiais", "Base municipal", "Mapa e revisão",
                       "Python e FastAPI", "SQLite", "geocodebr em Python", "MapLibre e OpenStreetMap", 'href="/projects"'):
            self.assertIn(marker, home)
        for marker in ("@media(max-width:680px)", "@media(max-width:580px)"):
            self.assertIn(marker, css)
        self.assertIn('router.add_api_route("/", page("home.html")', pages)
        self.assertIn("['/projects','Projetos']", ui)
        self.assertIn("['/','Início']", ui)
        self.assertIn('class="shell-brand" href="/"', ui)
        self.assertNotIn("⌖", ui + home)
        self.assertIn("height:72px", (root / "frontend" / "assets" / "app.css").read_text(encoding="utf-8"))
        fallback = (root / "frontend" / "assets" / "home-page.html").read_text(encoding="utf-8")
        projects = (root / "frontend" / "projects.html").read_text(encoding="utf-8")
        self.assertIn("location.replace('/assets/home-page.html')", projects)
        self.assertIn('class="site-footer"', fallback)
        for leaked in ("Exit code:", "Wall time:", "Output:"):
            self.assertNotIn(leaked, fallback)

    def test_project_workflow_has_overview_collapsible_stages_previews_and_completion_cards(self):
        root = Path(__file__).parent.parent / "frontend"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "assets" / "workflow.js").read_text(encoding="utf-8")
        styles = (root / "assets" / "workflow.css").read_text(encoding="utf-8")
        self.assertIn('/assets/workflow.css', html)
        self.assertIn('/assets/workflow.js', html)
        for marker in ("projectOverview", "VISÃO GERAL DO PROJETO", "makeCollapsible", "currentStage",
                       "Confirmar download oficial", "Confirmar preparação municipal", "Confirmar geocodificação",
                       "Dados oficiais disponíveis", "Base municipal concluída", "Geocodificação concluída",
                       "Ver detalhes técnicos"):
            self.assertIn(marker, script)
        for marker in (".project-overview", ".workflow-collapsible.collapsed", ".completion-card", "white-space:pre-line"):
            self.assertIn(marker, styles)


if __name__ == "__main__": unittest.main()
