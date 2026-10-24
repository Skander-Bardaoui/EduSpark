import re, io

files = [
    r"accounts/templates/accounts/prof_profile.html",
    r"courses/templates/courses/prof_course.html",
    r"exams/templates/exams/prof_corrections.html",
    r"coaching/templates/coaching/prof_followup.html",
]

def fix_class(m):
    cls = m.group(1)
    cls = cls.replace('text-[16px]', 'text-[18px]')
    return 'class="material-symbols-outlined ' + cls + '"'

pattern = re.compile(r'class="material-symbols-outlined ([^"]+)"')

for f in files:
    with io.open(f, encoding="utf-8") as fh:
        src = fh.read()
    new, n = pattern.subn(fix_class, src)
    with io.open(f, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    print(f"{f}: {n} spans processed")
