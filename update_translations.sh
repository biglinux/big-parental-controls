#!/bin/bash
set -e

DOMAIN="big-parental-controls"
SRC_DIR="src/big_parental_controls"
LOCALE_DIR="big-parental-controls/locale"
POT_FILE="$LOCALE_DIR/$DOMAIN.pot"
MO_BASE="big-parental-controls/usr/share/locale"

echo "=== $DOMAIN — update translations ==="

# 1. Extract translatable strings from Python sources + UI templates
echo "Extracting strings from Python sources..."
find "$SRC_DIR" -name '*.py' | sort > /tmp/bpc_files.txt

xgettext \
    --files-from=/tmp/bpc_files.txt \
    --language=Python \
    --keyword=_ \
    --keyword=N_ \
    --output="$POT_FILE" \
    --from-code=UTF-8 \
    --package-name="$DOMAIN" \
    --package-version="1.0" \
    --copyright-holder="BigLinux Team" \
    --msgid-bugs-address="biglinux@biglinux.com.br" \
    --add-comments=Note:

# Merge strings from .ui templates (translatable="yes" attributes)
echo "Extracting strings from UI templates..."
find "$SRC_DIR" -name '*.ui' | sort | while read -r ui_file; do
    xgettext \
        --join-existing \
        --language=Glade \
        --output="$POT_FILE" \
        --from-code=UTF-8 \
        "$ui_file"
done

echo "Generated $POT_FILE with $(grep -c '^msgid ' "$POT_FILE") strings."

# 2. Update existing .po files
echo "Updating PO files..."
for po_file in "$LOCALE_DIR"/*.po; do
    [ -f "$po_file" ] || continue
    echo "  Merging $po_file..."
    msgmerge --update --backup=none "$po_file" "$POT_FILE"
    msgattrib --no-obsolete -o "$po_file" "$po_file"
done

# 3. Compile .po → .mo and install to usr/share/locale tree
echo "Compiling MO files..."
rm -rf "$MO_BASE"
mkdir -p "$MO_BASE"
for po_file in "$LOCALE_DIR"/*.po; do
    [ -f "$po_file" ] || continue
    lang=$(basename "$po_file" .po)
    mo_dir="$MO_BASE/$lang/LC_MESSAGES"
    mkdir -p "$mo_dir"
    msgfmt -o "$mo_dir/$DOMAIN.mo" "$po_file"
    echo "  $lang → $mo_dir/$DOMAIN.mo"
done

# Cleanup
rm -f /tmp/bpc_files.txt

echo "=== Done. ==="
