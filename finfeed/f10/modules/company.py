import html as _html
import re
import sys

from finfeed.f10.http_client import _get_soup
from finfeed.f10.modules.concept import fuyao_info_get
from finfeed.f10.renderers.ascii_table import (
    _text_width,
    ascii_table,
    kv_table,
    kv_table_grouped,
    section_header,
)
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _wrap_disp
from finfeed.f10.utils.text import _clean_cell, _clean_soup, _norm_label, _norm_rendered_text


def _fetch_company_soup(code):
    url = f"https://basic.10jqka.com.cn/{code}/company.html"
    return _get_soup(url)


def render_company_detail(code, market_id="17", soup=None):
    if soup is None:
        soup = _fetch_company_soup(code)
        if soup is None:
            return f"{C.RED}请求失败{C.R}"
    detail = soup.find(id="detail")
    if not detail:
        return ""

    def _norm(s):
        return _norm_label(s)

    out_fields = []
    seen_labels = set()

    _SKIP_LABELS = {"薪酬", "持股数"}

    kv_re = re.compile(r"^(.{2,14}?)[：:]\s*(.+)$")
    for td in detail.find_all("td"):
        text = _clean_cell(td.get_text(" ", strip=True))
        if not text:
            continue
        m = kv_re.match(text)
        if not m:
            continue
        raw_label = m.group(1).strip()
        value = m.group(2).strip()
        norm_label = _norm(raw_label)

        if norm_label in _SKIP_LABELS:
            continue

        if norm_label in seen_labels:
            continue
        seen_labels.add(norm_label)

        if len(value) > 200:
            value = value[:200] + "…"
        out_fields.append((norm_label, value))

    exec_roles = {}
    for td_name in detail.select("td.name"):
        strong = td_name.find("strong", class_="hltip")
        strong_label = _norm(strong.get_text(strip=True).rstrip("：:")) if strong else ""

        name_span = td_name.find("span", recursive=False)
        if not name_span:
            continue
        name_a = name_span.find("a", recursive=False)
        if name_a:
            person_name = name_a.get_text(strip=True)
        else:
            continue

        if not person_name:
            continue

        jobs_td = td_name.find("td", class_="jobs")
        jobs_text = _clean_cell(jobs_td.get_text(" ", strip=True)) if jobs_td else ""

        role_checks = [
            ("董事长", lambda s, role: "董事长" in s or role == "董事长"),
            ("总经理", lambda s, role: "总经理" in s or role == "总经理"),
            ("总裁",   lambda s, role: ("总裁" in s and "副总裁" not in s) or role == "总裁"),
            ("董秘",   lambda s, role: "董事会秘书" in s or "董秘" in s or role in ("董事会秘书", "董秘")),
            ("法人代表", lambda s, role: "法人代表" in s or role == "法人代表"),
        ]
        for role_key, matcher in role_checks:
            if matcher(jobs_text, strong_label) and role_key not in exec_roles:
                exec_roles[role_key] = person_name

    for role_key in ["董事长", "总经理", "总裁", "董秘", "法人代表"]:
        person = exec_roles.get(role_key, "")
        if not person:
            continue
        replaced = False
        for i, (lbl, val) in enumerate(out_fields):
            if _norm(lbl) == role_key:
                out_fields[i] = (role_key, person)
                replaced = True
                break
        if not replaced:
            out_fields.append((role_key, person))

    for tw in detail.find_all("div", class_="tipbox_wrap"):
        parent_td = tw.find_parent("td")
        strong = parent_td.find("strong", class_="hltip") if parent_td else None
        label = _norm(strong.get_text(strip=True).rstrip("：:")) if strong else ""

        if label not in ("控股股东", "实际控制人", "最终控制人"):
            continue

        for popup in tw.find_all("div", class_="tipbox_wrap"):
            if popup != tw:
                popup.decompose()
        for popup in tw.find_all("div", class_="tipbox_hd"):
            popup.decompose()
        for popup in tw.find_all("div", class_="tipbox_bd"):
            popup.decompose()

        value = _clean_cell(tw.get_text(" ", strip=True))
        value = re.sub(r"^" + re.escape(label) + r"[：:]?\s*", "", value)
        value = re.sub(r"旗下上市公司一览.*", "", value, flags=re.S)
        value = value.strip()

        if not value:
            continue
        if len(value) > 200:
            value = value[:200] + "…"
        replaced = False
        for i, (lbl, val) in enumerate(out_fields):
            if lbl == label:
                out_fields[i] = (label, value)
                replaced = True
                break
        if not replaced:
            out_fields.append((label, value))

    api_data = {}
    try:
        resp = fuyao_info_get("company/v1/details_info/fields_completion",
                              {"code": code, "market": market_id, "type": "stock"})
        if resp.get("status_code") == 0:
            api_data = resp.get("data", {})
    except Exception as e:
        print(f"{C.DIM}[异常] company API: {e}{C.R}", file=sys.stderr)

    if api_data:
        _API_FIELDS = [
            ("注册地址",   "register_address"),
            ("会计事务所", "accounting_firm"),
            ("律师事务所", "lawyer_firm"),
        ]
        for cn_label, api_key in _API_FIELDS:
            value = api_data.get(api_key, "")
            if not value:
                continue
            already = False
            for lbl, _ in out_fields:
                if _norm(lbl) == cn_label:
                    already = True
                    break
            if not already:
                out_fields.append((cn_label, value))

    if not out_fields:
        return ""

    _GROUPS = [
        ("基本信息",   ["公司名称", "英文名称", "曾用名", "所属地域", "所属申万行业", "所属行业", "公司网址"]),
        ("董监高",     ["董事长", "总经理", "董秘", "法人代表", "总裁"]),
        ("资本信息",   ["注册资金", "员工人数"]),
        ("联系方式",   ["电话", "传真", "邮编", "办公地址", "注册地址"]),
        ("中介机构",   ["会计事务所", "律师事务所"]),
        ("业务简介",   ["主营业务", "产品名称", "公司简介", "公司介绍"]),
        ("股权结构",   ["控股股东", "实际控制人", "最终控制人"]),
    ]
    grouped = []
    used = set()
    for _gname, field_keys in _GROUPS:
        group_pairs = []
        for fk in field_keys:
            for i, (lbl, val) in enumerate(out_fields):
                if i in used:
                    continue
                if _norm(lbl) == fk:
                    group_pairs.append((lbl, val))
                    used.add(i)
                    break
        if group_pairs:
            grouped.append((_gname, group_pairs))
    leftover = [(lbl, val) for i, (lbl, val) in enumerate(out_fields) if i not in used]
    if leftover:
        grouped.append(("其他信息", leftover))

    return kv_table_grouped(grouped)


def _norm_history_para(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s(?=\d)", "", text)
    text = re.sub(r"(?<=\d)\s+(?=[,.\d])", "", text)
    return text.strip()


def _history_para_lines(p):
    raw = p.get_text("\n", strip=False)
    raw = _html.unescape(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\xa0", " ")
    lines = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[\s\.\.\.．…]*查看全部[▼]?[\s\.\.\.．…]*$", line):
            continue
        line = _norm_history_para(line)
        if line:
            lines.append(line)
    if len(lines) <= 1 and lines:
        split = re.sub(r"\s*(（[一二三四五六七八九十]+）)", r"\n\1", lines[0])
        lines = [x.strip() for x in split.split("\n") if x.strip()]
    return lines


def render_ipo_history(code, soup=None):
    if soup is None:
        soup = _fetch_company_soup(code)
        if soup is None:
            return ""
    _clean_soup(soup)

    hdr = None
    for h in soup.find_all(["h2", "h3"]):
        if "发行相关" in h.get_text():
            hdr = h
            break
    if not hdr:
        return ""

    for sib in hdr.find_all_next():
        if sib.name in ("h2", "h3"):
            break
        if sib.name != "table":
            continue
        for td in sib.find_all("td"):
            raw = td.get_text(" ", strip=True)
            if not raw or "历史沿革" not in raw:
                continue

            paragraphs = td.find_all("p")
            if not paragraphs:
                m = re.search(r"^历史沿革[：:]\s*(.+)$", raw, re.S)
                if not m:
                    return ""
                value = m.group(1).strip()
                value = re.sub(r"\s*(（[一二三四五六七八九十]+）)", r"\n\1", value)
                lines = [_norm_history_para(x) for x in value.splitlines()
                         if _norm_history_para(x)]
                out = []
                for line in lines:
                    is_section = bool(re.match(r"^（[一二三四五六七八九十]+）", line))
                    if is_section and out:
                        out.append("")
                    for seg in _wrap_disp(line, _text_width()):
                        out.append(f"  {seg}")
                return "\n".join(out)

            lines = []
            has_full = False
            for p in paragraphs:
                p_lines = _history_para_lines(p)
                if not p_lines:
                    continue
                p_text = " ".join(p_lines)
                if "历史沿革" in p_text:
                    p_lines = [x for x in p_lines if "历史沿革" not in x]
                    if not p_lines:
                        continue
                if re.match(r"^[\s\.\.\.]*查看全部[▼]?[\s\.\.\.]*$", p_text):
                    continue
                p_cls = p.get("class") or []
                if isinstance(p_cls, (list, tuple)):
                    p_cls = " ".join(str(c) for c in p_cls)
                else:
                    p_cls = str(p_cls)
                if "none" in p_cls or "hidden" in p_cls:
                    has_full = True
                    lines = p_lines
                else:
                    if not has_full:
                        lines.extend(p_lines)

            if not lines:
                return ""

            tw = _text_width()
            out = []
            for line in lines:
                is_section = bool(re.match(r"^（[一二三四五六七八九十]+）", line))
                if is_section and out:
                    out.append("")
                for seg in _wrap_disp(line, tw):
                    out.append(f"  {seg}")
            return "\n".join(out)
    return ""


def render_ipo_info(code, soup=None):
    if soup is None:
        soup = _fetch_company_soup(code)
        if soup is None:
            return ""
    _clean_soup(soup)

    hdr = None
    for h in soup.find_all(["h2", "h3"]):
        if "发行相关" in h.get_text():
            hdr = h
            break
    if not hdr:
        return ""

    def _norm(s):
        return _norm_label(s)

    pairs = []
    seen_labels = set()
    kv_re = re.compile(r"^(.{2,14}?)[：:]\s*(.+)$")
    inner_kv_re = re.compile(r"^(.+?)\s+(上市保荐人|上市推荐人)[：:]\s*(.+)$", re.S)
    _IPO_SKIP = {"历史沿革"}

    for sib in hdr.find_all_next():
        if sib.name in ("h2", "h3"):
            break
        if sib.name == "table":
            for td in sib.find_all("td"):
                text = _clean_cell(td.get_text(" ", strip=True))
                if not text:
                    continue
                m = kv_re.match(text)
                if not m:
                    continue
                raw_label = m.group(1).strip()
                value = m.group(2).strip()
                norm_label = _norm(raw_label)

                if norm_label in _IPO_SKIP:
                    continue

                inner_m = inner_kv_re.match(value)
                if inner_m:
                    main_value = inner_m.group(1).strip()
                    if norm_label not in seen_labels:
                        pairs.append((norm_label, main_value))
                        seen_labels.add(norm_label)
                    inner_label = _norm(inner_m.group(2).strip())
                    inner_value = inner_m.group(3).strip()
                    if inner_label not in seen_labels:
                        pairs.append((inner_label, inner_value))
                        seen_labels.add(inner_label)
                else:
                    if norm_label not in seen_labels:
                        pairs.append((norm_label, value))
                        seen_labels.add(norm_label)

    if not pairs:
        return ""

    _IPO_GROUPS = [
        ("上市日期",   ["成立日期", "上市日期"]),
        ("发行参数",   ["发行数量", "发行价格", "发行市盈率", "发行中签率"]),
        ("募资信息",   ["预计募资", "实际募资"]),
        ("中介机构",   ["主承销商", "上市保荐人", "上市推荐人"]),
    ]
    grouped = []
    used = set()
    for _gname, field_keys in _IPO_GROUPS:
        group_pairs = []
        for fk in field_keys:
            for i, (lbl, val) in enumerate(pairs):
                if i in used:
                    continue
                if _norm(lbl) == fk:
                    group_pairs.append((lbl, val))
                    used.add(i)
                    break
        if group_pairs:
            grouped.append((_gname, group_pairs))
    leftover = [(lbl, val) for i, (lbl, val) in enumerate(pairs) if i not in used]
    if leftover:
        grouped.append(("其他", leftover))
    return kv_table_grouped(grouped)


def _render_execs_tab(tb, job_overrides=None):
    if not tb:
        return ""
    job_overrides = job_overrides or {}
    meta = {}
    for td in tb.select("td.title"):
        nm = _clean_cell(td.get_text(strip=True))
        if not nm:
            continue
        tr = td.find_parent("tr")
        nxt = tr.find_next_sibling("tr") if tr else None
        intro = sal = term = ""
        for dcell in tr.select("td.date") if tr else []:
            dtext = dcell.get_text(" ", strip=True)
            if "本届任期" in dtext:
                term = re.sub(r"本届任期[：:]?\s*", "", dtext)
                term = re.sub(r"\s+", " ", term).strip()
                break
        if nxt:
            it = nxt.select_one("td.intro")
            sa = nxt.select_one("td.salary")
            intro = _clean_cell(it.get_text(strip=True)) if it else ""
            if sa:
                sal = _clean_cell(sa.get_text(strip=True)).replace("薪酬：", "").strip()
        meta.setdefault(nm, (intro, sal, term))

    uniq, seen = [], set()
    for nd in tb.select("td.name"):
        raw = nd.get_text(" ", strip=True)
        nm = raw.split()[0] if raw.split() else ""
        nm = re.sub(r"[×✕✖╳]", "", nm).strip()
        if not nm or nm in seen:
            continue
        seen.add(nm)
        sibs = nd.find_next_siblings("td")
        vals = [_clean_cell(x.get_text(" ", strip=True)) for x in sibs[:3]]
        job = vals[0] if len(vals) > 0 else ""
        full_job = job_overrides.get(nm, "")
        if (_exec_job_can_override(job, full_job) and
                _exec_job_score(full_job) > _exec_job_score(job)):
            job = full_job
        direct = vals[1] if len(vals) > 1 else ""
        indirect = vals[2] if len(vals) > 2 else ""
        intro, sal, term = meta.get(nm, ("", "", ""))
        uniq.append([nm, job, term, intro, sal, direct, indirect])

    if not uniq:
        return ""
    rows = [["姓名", "职务", "本届任期", "性别/年龄/学历",
             "薪酬", "直接持股", "间接持股"]] + uniq
    return ascii_table(rows, colcap=30)


def _exec_job_score(job):
    if not job:
        return 0
    parts = [p.strip() for p in re.split(r"[,，、/]+", job) if p.strip()]
    committee_bonus = sum(1 for p in parts if "委员会" in p)
    return len(parts) * 10 + committee_bonus * 20 + min(len(job), 80)


def _exec_job_parts(job):
    return {p.strip() for p in re.split(r"[,，、/]+", job or "") if p.strip()}


def _exec_job_can_override(current, candidate):
    if not candidate:
        return False
    if not current:
        return True
    current_parts = _exec_job_parts(current)
    candidate_parts = _exec_job_parts(candidate)
    return bool(current_parts & candidate_parts)


def _collect_exec_job_overrides(soup):
    jobs_by_name = {}
    for jobs_td in soup.select("td.jobs"):
        tr = jobs_td.find_parent("tr")
        title_td = tr.select_one("td.title") if tr else None
        if not title_td:
            continue
        name = _clean_cell(title_td.get_text(" ", strip=True))
        job = _clean_cell(jobs_td.get_text(" ", strip=True))
        if not name or name in ("?", "--") or not job or job in ("?", "--"):
            continue
        old = jobs_by_name.get(name, "")
        if _exec_job_score(job) > _exec_job_score(old):
            jobs_by_name[name] = job
    return jobs_by_name


def render_execs(code, soup=None):
    if soup is None:
        soup = _fetch_company_soup(code)
        if soup is None:
            return f"{C.RED}请求失败{C.R}"
    hdr = None
    for h in soup.find_all(["h2", "h3"]):
        if "高管介绍" in h.get_text():
            hdr = h
            break
    if not hdr:
        return ""

    tab_labels = {}
    for a in hdr.find_all_next():
        if a.name in ("h2",):
            break
        if a.name == "a":
            targ = a.get("targ")
            if targ and str(targ).startswith("ml_"):
                tab_labels[str(targ)] = a.get_text(strip=True)
    if not tab_labels:
        tb = hdr.find_next("table")
        return _render_execs_tab(tb, job_overrides=_collect_exec_job_overrides(soup))

    job_overrides = _collect_exec_job_overrides(soup)

    parts = []
    for tid in sorted(tab_labels.keys()):
        div = soup.find(id=tid)
        if not div:
            continue
        tb = div.find("table")
        if not tb:
            continue
        rendered = _render_execs_tab(tb, job_overrides=job_overrides)
        if not rendered:
            continue
        label = tab_labels[tid]

        bio_lines = []
        for pt in div.find_all("div", class_=lambda c: c and "person_table" in str(c)):
            gg = pt.find("table", class_="ggintro")
            if not gg:
                continue
            pname = bio_text = ""
            for tr2 in gg.find_all("tr"):
                tds = tr2.find_all("td")
                if not tds:
                    continue
                if not pname:
                    pname = tds[0].get_text(strip=True)
                if len(tds) == 1 and tds[0].get("colspan"):
                    bio_text = _clean_cell(tds[0].get_text(" ", strip=True))
                    if pname and bio_text.startswith(pname):
                        # 同花顺简介开头为 "姓名：…" 或 "姓名，…"，剥掉名字后
                        # 一并去掉分隔符（全/半角冒号、中文逗号、空格）
                        bio_text = bio_text[len(pname):].lstrip(" ，：:：: ").lstrip()
                    break
            if not bio_text or not pname:
                continue
            bio_lines.append((pname, bio_text))

        if bio_lines:
            out_lines = [rendered, ""]
            for i, (pname, bio_text) in enumerate(bio_lines):
                out_lines.append(f"  ◆ {pname}")
                out_lines.append(f"    {bio_text}")
                if i != len(bio_lines) - 1:
                    out_lines.append("")
            rendered = "\n".join(out_lines).rstrip()

        parts.append(f"{section_header(label, 'sub')}\n{rendered}")
    if not parts:
        tb = hdr.find_next("table")
        rendered = _render_execs_tab(tb, job_overrides=job_overrides)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(parts)


def render_company_summary_api(code, market_id):
    try:
        j = fuyao_info_get("company/v1/details_info/fields_completion",
                           {"code": code, "market": market_id, "type": "stock"})
        if j.get("status_code") != 0:
            return ""
        data = j.get("data", {})
        if not data:
            return ""
        pairs = []
        for key, label in [
            ("company_name", "公司简称"),
            ("company_full_name", "公司全称"),
            ("legal_person", "法人代表"),
            ("chairman", "董事长"),
            ("general_manager", "总经理"),
            ("secretary", "董事会秘书"),
            ("register_capital", "注册资本"),
            ("employees", "员工人数"),
            ("office_address", "办公地址"),
            ("register_address", "注册地址"),
            ("accounting_firm", "会计事务所"),
            ("lawyer_firm", "律师事务所"),
            ("business_scope", "主营业务"),
        ]:
            val = data.get(key)
            if val:
                pairs.append((label, str(val)))
        if not pairs:
            return ""
        out = [section_header("公司概要"),
               _norm_rendered_text(kv_table(pairs)), ""]
        return "\n".join(out)
    except Exception:
        return ""
