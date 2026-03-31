# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# ソースコードのパスを追加
sys.path.insert(0, os.path.abspath("../impl/src"))

# -- Project information -----------------------------------------------------
project = "Beads Sorter"
copyright = "2026, Beads Sorter Team"
author = "Beads Sorter Team"
release = "0.1.0"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx_needs",
    "myst_parser",
]

templates_path = []
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# 日本語対応
language = "ja"

# -- Options for HTML output -------------------------------------------------
html_theme = "shibuya"
html_static_path = []

# -- Options for todo extension ----------------------------------------------
todo_include_todos = True

# -- Options for intersphinx extension ---------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Options for sphinx-needs ------------------------------------------------
needs_types = [
    {
        "directive": "req",
        "title": "Requirement",
        "prefix": "REQ_",
        "color": "#BFD8D2",
        "style": "node",
    },
    {
        "directive": "spec",
        "title": "Specification",
        "prefix": "SPEC_",
        "color": "#FEDCD2",
        "style": "node",
    },
    {
        "directive": "impl",
        "title": "Implementation",
        "prefix": "IMPL_",
        "color": "#DF744A",
        "style": "node",
    },
    {
        "directive": "test",
        "title": "Test Case",
        "prefix": "TEST_",
        "color": "#DCB239",
        "style": "node",
    },
]
