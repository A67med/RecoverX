"""Safe, metadata-only PDF case summary for examiner review.

The PDF is not a legal chain-of-custody certificate. No recovered file content
is opened or included, and no report data is executed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from ..forensic.case_store import Case

NAVY = colors.HexColor('#102237')
TEAL = colors.HexColor('#137e79')
INK = colors.HexColor('#203242')
MUTED = colors.HexColor('#536679')
LIGHT = colors.HexColor('#f0f6f8')


def _p(text, style):
    # Limit report fields and escape any source-supplied characters used in XML.
    return Paragraph(escape(str(text if text is not None else '-')[:900]), style)


def generate_case_pdf(case: Case) -> bytes:
    """Return a PDF report with actual case/run data; empty cases are supported."""
    rec = case.load()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(612, 792), rightMargin=42, leftMargin=42,
                            topMargin=46, bottomMargin=49, title=f"RecoverX case {case.id}",
                            author="RecoverX (metadata-only report)")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RXTitle', parent=styles['Title'], fontName='Helvetica-Bold',
                              textColor=NAVY, fontSize=24, leading=28, spaceAfter=4))
    styles.add(ParagraphStyle(name='RXHeader', parent=styles['Heading2'], fontName='Helvetica-Bold',
                              textColor=NAVY, fontSize=12.5, spaceBefore=15, spaceAfter=8))
    styles.add(ParagraphStyle(name='RXBody', parent=styles['Normal'], fontName='Helvetica',
                              textColor=INK, fontSize=8.8, leading=12.7))
    styles.add(ParagraphStyle(name='RXSmall', parent=styles['Normal'], fontName='Helvetica',
                              textColor=MUTED, fontSize=7.8, leading=11))
    styles.add(ParagraphStyle(name='RXCell', parent=styles['Normal'], fontName='Helvetica',
                              textColor=INK, fontSize=8.5, leading=11, alignment=TA_LEFT))
    body, small, cell = styles['RXBody'], styles['RXSmall'], styles['RXCell']

    def section(name):
        story.append(_p(name, styles['RXHeader']))

    def facts(rows):
        data = [[_p(key, cell), _p(value, cell)] for key, value in rows]
        t = Table(data, colWidths=[135, 390], hAlign='LEFT', splitByRow=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), LIGHT), ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 9), ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LINEBELOW', (0,0), (-1,-1), .45, colors.HexColor('#dae5ea'))
        ]))
        story.append(t)

    story = [_p('RECOVERX  /  FORENSIC CASE REPORT', styles['RXTitle']),
             _p('Generated: ' + datetime.now(timezone.utc).isoformat(timespec='seconds'), small),
             Spacer(1, 10)]
    section('Case information')
    facts([('Case ID', rec.get('case_id', case.id)), ('Label', rec.get('label') or '-'),
           ('Examiner', rec.get('examiner') or '-'), ('Created (UTC)', rec.get('created_at') or '-'),
           ('Status', rec.get('status') or '-'), ('Disk image', rec.get('image_path') or '-'),
           ('Image size (bytes)', rec.get('image_size') or 0),
           ('Evidence SHA-256 at creation', rec.get('image_sha256_initial') or 'NOT BASELINED')])
    story.append(Spacer(1,8))
    if rec.get('last_hash_check'):
        last = rec['last_hash_check']
        story.append(_p('Last integrity check: ' + ('UNCHANGED' if last.get('unchanged') else 'FAILED')
                        + '  /  ' + str(last.get('at', '-')), body))
    section('Recovery runs')
    runs = rec.get('runs', [])
    if not runs:
        story.append(_p('No recovery runs have been recorded for this case.', body))
    for run in runs:
        r_metrics = run.get('metrics') or {}
        strategy = (run.get('selection') or {}).get('strategy_used') or 'unknown'
        story.append(KeepTogether([
            _p('Run ' + str(run.get('run_id', 'unknown')), styles['RXHeader']),
            _p(f"Started: {run.get('started_at', '-')}    Finished: {run.get('finished_at', '-')}" ,small),
            _p(f"Method: {run.get('method')}    Strategy: {strategy}    Status: {run.get('status')}",body),
            _p(f"Source unchanged: {run.get('source_unchanged')}    Recovered outputs: {r_metrics.get('outputs', 0)}    Distinct contents: {r_metrics.get('distinct_contents', 0)}",body),
            _p(f"Verified exact matches: {r_metrics.get('exact_recovered', 'not measured (no ground truth)')}    Total time: {(run.get('timing') or {}).get('total_s', '-')} s",body),
        ]))
        engines = run.get('engine_runs') or []
        if engines:
            facts([('Engine ' + str(e.get('engine')), f"{e.get('status')} | {len(e.get('files') or [])} files | {e.get('elapsed_s', '-')} s | {e.get('error') or 'no error'}") for e in engines])
        recovered = [(str(e.get('engine', '-')), f) for e in engines for f in e.get('files', [])]
        if recovered:
            story.append(Spacer(1, 7))
            story.append(_p(f'Recovered output metadata (first {min(30, len(recovered))} of {len(recovered)}):', small))
            rows = [[_p(col, small) for col in ('Engine', 'Recovered name', 'SHA-256', 'Verification')]]
            for engine, f in recovered[:30]:
                rows.append([_p(engine, small), _p(f.get('recovered_name', '-')[:80], small),
                             _p(f.get('sha256', '-')[:70], small),
                             _p(f.get('integrity_state', 'unknown'), small)])
            outputs = Table(rows, colWidths=[65, 115, 224, 121], repeatRows=1, hAlign='LEFT')
            outputs.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), LIGHT),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LINEBELOW', (0,0), (-1,0), 1, TEAL),
                ('LINEBELOW', (0,1), (-1,-1), .3, colors.HexColor('#dae5ea')),
                ('LEFTPADDING', (0,0), (-1,-1), 4), ('RIGHTPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(outputs)
            if len(recovered) > 30:
                story.append(_p('Remaining files and full-length hashes are available in the JSON manifest and CSV export.', small))
        story.append(Spacer(1, 9))
    section('Evidence and audit limitations')
    story.append(_p('Recovered files are listed by metadata and SHA-256 in the JSON manifest and CSV export. '
                    'A recovered output is not confirmed to match a deleted original unless a valid ground-truth '
                    'manifest is supplied. This summary supports review and auditability but does not itself '
                    'establish chain of custody, original ownership, or legal admissibility.', body))
    story.append(Spacer(1,9))
    story.append(_p('This report was generated from the saved case records without accessing recovered-file contents.',small))

    def foot(canvas, _document):
        canvas.setStrokeColor(colors.HexColor('#d6e5e9'))
        canvas.line(42, 35, 570, 35)
        canvas.setFillColor(MUTED)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(42, 24, 'RecoverX | Case summary | Not a legal certification')
        canvas.drawRightString(570, 24, f'Page {_document.page}')
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()
