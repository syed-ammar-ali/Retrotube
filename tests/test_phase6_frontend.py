"""Automated tests for Phase 6: Frontend templates, macros, and retro styling."""
from pathlib import Path

from core.templates import templates

BASE_DIR = Path(__file__).resolve().parent.parent
CSS_PATH = BASE_DIR / "static" / "css" / "retro.css"
TEMPLATES_DIR = BASE_DIR / "templates"


def test_all_templates_syntax_valid():
    """Verify that all 15 Jinja2 templates parse and compile without syntax errors."""
    template_files = list(TEMPLATES_DIR.glob("*.html"))
    assert len(template_files) >= 15

    for tpl_file in template_files:
        # get_template parses and compiles AST
        tpl = templates.env.get_template(tpl_file.name)
        assert tpl is not None


def test_macros_star_rating_render():
    """Verify the stars macro clips and renders half-star percentages properly."""
    macro_src = """
    {% import '_macros.html' as m %}
    {{ m.stars(5.0) }}
    {{ m.stars(4.3) }}
    {{ m.stars(2.5) }}
    {{ m.stars(0.0) }}
    """
    tpl = templates.env.from_string(macro_src)
    rendered = tpl.render()

    # 5.0 stars -> 100% width
    assert 'width:100%' in rendered
    # 4.3 stars -> round(8.6) = 9 -> 90% width
    assert 'width:90%' in rendered
    # 2.5 stars -> round(5.0) = 5 -> 50% width
    assert 'width:50%' in rendered
    # 0.0 stars -> 0% width
    assert 'width:0%' in rendered


def test_macros_pagination_render():
    """Verify classic YouTube pagination: Pages: 1 2 3 4 5 Next."""
    macro_src = """
    {% import '_macros.html' as m %}
    {{ m.pagination('/browse?page=', 2, 5) }}
    """
    tpl = templates.env.from_string(macro_src)
    rendered = tpl.render()

    assert '<span class="lead">Pages:</span>' in rendered
    assert '<span class="current">2</span>' in rendered
    assert '<a href="/browse?page=1">1</a>' in rendered
    assert '<a href="/browse?page=3">3</a>' in rendered
    assert '<a href="/browse?page=3">Next</a>' in rendered


def test_retro_css_tokens():
    """Verify CSS variables match 2006-07 design notes."""
    assert CSS_PATH.exists()
    content = CSS_PATH.read_text(encoding="utf-8")

    # Fixed 875px container
    assert "#container { width: 875px;" in content or "875px" in content
    # Pastel blue tab color
    assert "#BBCCEE" in content
    # Arial 12px
    assert "Arial" in content
    # Link color
    assert "#0033CC" in content
    # Star SVG data URIs
    assert "--star-full" in content
    assert "--star-empty" in content
