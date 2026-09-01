import csv
import io


ANALYTICS_EVENTS = []


def track_export(row_count):
    ANALYTICS_EVENTS.append({"event": "csv_export", "rows": row_count})


def export_rows(rows):
    output = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else []
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    track_export(len(rows))
    return output.getvalue()

