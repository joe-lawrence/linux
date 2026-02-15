#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Generate patch that touches many files for line recount testing
#
# Usage: generate.sh <kernel_src_dir> <output_patch_file>

set -e
set -o pipefail

SRC_DIR="$1"
PATCH_FILE="$2"

if [[ -z "$SRC_DIR" ]] || [[ -z "$PATCH_FILE" ]]; then
    echo "Usage: $0 <kernel_src_dir> <output_patch_file>" >&2
    exit 1
fi

cd "$SRC_DIR"

# Build list of .c files we'll modify (same filter as the modify step below)
MODIFIED_FILES=$(git ls-files '*.c' | grep -v '^lib/')

# Check only the .c files we intend to modify for uncommitted changes
if [[ -n $(echo "$MODIFIED_FILES" | xargs git diff --name-only --) ]] || \
   [[ -n $(echo "$MODIFIED_FILES" | xargs git diff --cached --name-only --) ]]; then
    echo "Error: Working tree has uncommitted changes to .c files we need to modify." >&2
    echo "Please commit or stash changes before running this test." >&2
    echo "This test temporarily modifies many .c files to generate a patch." >&2
    exit 1
fi

# Ensure restoration on exit (success or failure) - only restore files we modify
cleanup() {
    echo "Restoring working tree..." >&2
    echo "$MODIFIED_FILES" | xargs git restore -- 2>/dev/null || true
}
trap cleanup EXIT

echo "Modifying .c files..." >&2

# Modify all tracked .c files (excludes gitignored generated files) except lib/
echo "$MODIFIED_FILES" | xargs sed -i '1iasm("nop");'

echo "Restoring excluded files..." >&2

# Restore files that shouldn't be modified
git checkout HEAD -- \
    tools \
    arch/x86/lib/inat.c \
    arch/x86/lib/insn.c \
    kernel/configs.c \
    2>/dev/null || true

echo "Generating patch..." >&2

# Generate patch with header
cat > "$PATCH_FILE" << 'EOF'
From: Test Author <test@example.com>
Subject: [PATCH] Add nop to many files (line recount test)

Add asm("nop"); to many .c files to test klp-build's line number
recounting feature. Since asm("nop") produces no object code changes,
klp-build should detect no changes and fail with "no changes detected".

EOF

# Append the diff
git diff --no-color >> "$PATCH_FILE"

# Count modified files
NUM_FILES=$(git diff --name-only | wc -l)
echo "Generated patch touching $NUM_FILES files" >&2

# Cleanup happens via trap
