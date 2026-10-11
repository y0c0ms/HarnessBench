def title_case(s):
    out, start = [], True
    for ch in s:
        if ch.isspace():
            out.append(ch)
            start = True
        else:
            out.append(ch.upper() if start else ch)
            start = False
    return "".join(out)
