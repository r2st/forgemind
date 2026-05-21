#!/usr/bin/env bash
# Finds PAT_truefoundry_knol.txt (which the browser downloaded) and copies
# it into /Users/dev/projects/claudeplus/keys/PAT_truefoundry_knol.
set -e
DEST=/Users/dev/projects/claudeplus/keys/PAT_truefoundry_knol

# Look in standard download locations first.
for cand in \
  ~/Downloads/PAT_truefoundry_knol.txt \
  ~/Downloads/PAT_truefoundry_knol \
  ~/Desktop/PAT_truefoundry_knol.txt; do
  if [[ -f "$cand" ]]; then
    SRC="$cand"
    break
  fi
done

# Fallback: spotlight search if not in standard paths.
if [[ -z "${SRC:-}" ]]; then
  SRC=$(mdfind -name 'PAT_truefoundry_knol' 2>/dev/null | head -1)
fi

if [[ -z "${SRC:-}" || ! -f "$SRC" ]]; then
  echo "ERROR: PAT_truefoundry_knol.txt not found. Look in your Downloads folder."
  echo "Press any key to close."; read -n 1
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
cat "$SRC" | tr -d '\r\n ' > "$DEST"
chmod 600 "$DEST"
size=$(wc -c < "$DEST" | tr -d ' ')
echo "Source: $SRC"
echo "Wrote $size bytes to $DEST"
echo
echo "Done. You can close this window."
sleep 3
