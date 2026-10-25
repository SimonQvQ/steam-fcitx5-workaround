# Vendored Fcitx5 GTK sources

This directory contains the build-required subset of [fcitx/fcitx5-gtk](https://github.com/fcitx/fcitx5-gtk), tag **5.1.7**, commit `3b18d2ab7401d4233daf38bbc5896f1703685a43`.

The upstream source files retain their copyright headers and **LGPL-2.1-or-later** SPDX identifiers. The corresponding license text is included in `fcitx5-gtk/LICENSES/` and at the repository root.

The vendored files are kept unmodified. Build-time changes are isolated in `../patches/glib-2.66.patch` and applied to `.build/sources/`. Generated marshaller/config headers are created in `.build/objects/`.

`SHA256SUMS.json` detects accidental changes to this source subset. It is a local integrity manifest, not an independent signature of upstream authenticity. `SOURCE.json` records the upstream identity and selection.
