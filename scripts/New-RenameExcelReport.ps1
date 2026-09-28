# =============================================================================
# New-RenameExcelReport.ps1
# =============================================================================
# Generates a formatted Excel spreadsheet from the rename plan CSV for
# user review.  Uses Python + openpyxl (must be installed).
#
# The spreadsheet includes:
#   - Colour-coded confidence rows (green/yellow/orange/grey)
#   - Frozen header row with autofilter
#   - An "Approved" column for the user to mark yes/no
#   - An "Edited Filename" column for manual corrections
#   - Column widths tuned for readability
#
# Called by Rename-UnfiledVideos.ps1; can also be run standalone:
#   .\New-RenameExcelReport.ps1 -CsvPath .\unfiled-rename-plan.csv
#
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CsvPath,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $CsvPath)) {
    Write-Error "CSV not found: $CsvPath"
    exit 1
}

if (-not $OutputPath) {
    $OutputPath = [System.IO.Path]::ChangeExtension($CsvPath, ".xlsx")
}

# Resolve to absolute paths for Python
# Use .NET to get plain filesystem paths (Resolve-Path on UNC returns
# provider-qualified paths like "Microsoft.PowerShell.Core\FileSystem::\\..."
# which Python can't open)
$csvFull = (Get-Item -LiteralPath $CsvPath).FullName
if (Test-Path $OutputPath) {
    $excelFull = (Get-Item -LiteralPath $OutputPath).FullName
} else {
    # Output doesn't exist yet - construct the path manually
    $excelFull = [System.IO.Path]::GetFullPath($OutputPath)
}

$pythonScript = @"
import sys
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

csv_path = r'$csvFull'
xlsx_path = r'$excelFull'

# Read CSV
with open(csv_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    headers = reader.fieldnames

if not rows:
    print("ERROR: CSV is empty")
    sys.exit(1)

# Create workbook
wb = Workbook()
ws = wb.active
ws.title = "Rename Plan"

# --- Styles ---
header_font = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
header_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

thin_border = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)

# Confidence-based row fills
conf_fills = {
    'High':   PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid'),  # light green
    'Medium': PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid'),  # light yellow
    'Low':    PatternFill(start_color='FCE4D6', end_color='FCE4D6', fill_type='solid'),  # light orange
    'None':   PatternFill(start_color='F2F2F2', end_color='F2F2F2', fill_type='solid'),  # light grey
}

wrap_align = Alignment(vertical='top', wrap_text=True)
top_align = Alignment(vertical='top')

# --- Build output columns ---
# Add review columns at the end
output_cols = list(headers) + ['Approved', 'Edited Filename', 'Review Notes']
col_indices = {name: i+1 for i, name in enumerate(output_cols)}

# --- Write header row ---
for col_name in output_cols:
    col_idx = col_indices[col_name]
    cell = ws.cell(row=1, column=col_idx, value=col_name)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = header_align
    cell.border = thin_border

# --- Write data rows ---
for row_idx, row in enumerate(rows, start=2):
    conf = row.get('Confidence', '')
    fill = conf_fills.get(conf, conf_fills['None'])

    for col_name in output_cols:
        col_idx = col_indices[col_name]
        value = row.get(col_name, '')
        cell = ws.cell(row=row_idx, column=col_idx, value=value)
        cell.fill = fill
        cell.border = thin_border

        # Wrap text for long columns, top-align for all
        if col_name in ('OldFilename', 'NewFilename', 'Description', 'Edited Filename', 'Review Notes'):
            cell.alignment = wrap_align
        else:
            cell.alignment = top_align

# --- Column widths ---
col_widths = {
    'OldFilename':       60,
    'NewFilename':       55,
    'EpornerID':         14,
    'LeadingToken':      16,
    'Subcategory':       12,
    'MatchedPerformers': 25,
    'MatchedStudio':     18,
    'Confidence':        12,
    'Resolution':        10,
    'Description':       50,
    'Notes':             22,
    'Approved':          10,
    'Edited Filename':   55,
    'Review Notes':      30,
}

for col_name, width in col_widths.items():
    if col_name in col_indices:
        col_idx = col_indices[col_name]
        ws.column_dimensions[get_column_letter(col_idx)].width = width

# --- Freeze header row and first column ---
ws.freeze_panes = 'B2'

# --- Autofilter on all columns ---
last_col = get_column_letter(len(output_cols))
ws.auto_filter.ref = f'A1:{last_col}{len(rows)+1}'

# --- Create a summary sheet ---
ws2 = wb.create_sheet("Summary")
summary_data = [
    ('Total files', len(rows)),
    ('', ''),
    ('By Confidence:', ''),
]

conf_counts = {}
for r in rows:
    c = r.get('Confidence', 'None')
    conf_counts[c] = conf_counts.get(c, 0) + 1

for conf in ['High', 'Medium', 'Low', 'None']:
    summary_data.append((f'  {conf}', conf_counts.get(conf, 0)))

summary_data.append(('', ''))
summary_data.append(('By Leading Token:', ''))

lt_counts = {}
for r in rows:
    lt = r.get('LeadingToken', 'UI')
    if r.get('MatchedPerformers', ''):
        lt_counts['Performer-led'] = lt_counts.get('Performer-led', 0) + 1
    elif lt != 'UI':
        lt_counts[f'Category-led ({lt})'] = lt_counts.get(f'Category-led ({lt})', 0) + 1
    elif r.get('MatchedStudio', ''):
        lt_counts['Studio-led'] = lt_counts.get('Studio-led', 0) + 1
    else:
        lt_counts['UI (Unidentified)'] = lt_counts.get('UI (Unidentified)', 0) + 1

for lt_label in sorted(lt_counts.keys()):
    summary_data.append((f'  {lt_label}', lt_counts.get(lt_label, 0)))

summary_data.append(('', ''))
summary_data.append(('Instructions:', ''))
summary_data.append(('  1. Review each row in the Rename Plan sheet', ''))
summary_data.append(('  2. Set "Approved" to yes if the proposed filename is correct', ''))
summary_data.append(('  3. If the filename needs changes, enter it in "Edited Filename"', ''))
summary_data.append(('  4. Use "Review Notes" for any comments', ''))
summary_data.append(('  5. Filter by Confidence to focus on High/Medium first', ''))

for row_idx, (label, value) in enumerate(summary_data, start=1):
    cell_a = ws2.cell(row=row_idx, column=1, value=label)
    cell_b = ws2.cell(row=row_idx, column=2, value=value)
    if label and not label.startswith('  ') and label.endswith(':'):
        cell_a.font = Font(bold=True)
    if isinstance(value, int):
        cell_b.alignment = Alignment(horizontal='right')

ws2.column_dimensions['A'].width = 45
ws2.column_dimensions['B'].width = 15

# --- Save ---
wb.save(xlsx_path)
print(f"OK: Excel file written to {xlsx_path} ({len(rows)} rows)")
"@

# Write the Python script to a temp file and execute it
$tempPy = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), ".py")
Set-Content -LiteralPath $tempPy -Value $pythonScript -Encoding UTF8

try {
    $result = python $tempPy 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Output $result
    } else {
        Write-Error "Python script failed: $result"
    }
} finally {
    Remove-Item -LiteralPath $tempPy -Force -ErrorAction SilentlyContinue
}
