from finfeed.f10.http_client import _get_soup
from finfeed.f10.renderers.ascii_table import ascii_table


def render_holder_count(code, periods=10):
    url = f"https://basic.10jqka.com.cn/{code}/holder.html"
    soup = _get_soup(url)
    if not soup:
        return ""
    el = soup.select_one("#gdrsTable")
    if not el:
        return ""
    tables = el.find_all("table")
    if len(tables) < 4:
        return ""
    metrics = [r.get_text(" ", strip=True) for r in tables[1].find_all("tr")]
    drow = tables[2].find_all("tr")
    dates = ([c.get_text(" ", strip=True) for c in drow[0].find_all(["td", "th"])]
             if drow else [])
    data = []
    for tr in tables[3].find_all("tr"):
        row = []
        for c in tr.find_all(["td", "th"]):
            v = c.get_text(" ", strip=True).split(" ")[0]
            row.append(v)
        data.append(row)
    if not metrics or not dates or not data:
        return ""
    n = min(periods, len(dates))
    rows = [["指标"] + dates[:n]]
    for i, m in enumerate(metrics):
        if i < len(data):
            rows.append([m] + data[i][:n])
    return ascii_table(rows, colcap=14)
