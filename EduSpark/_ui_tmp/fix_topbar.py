import re, io

path = r"templates/portal/_topbar.html"
with io.open(path, encoding="utf-8") as f:
    src = f.read()

def fix_class(m):
    cls = m.group(1)
    cls = cls.replace('text-[14px]', 'text-[18px]')
    cls = cls.replace('text-[16px]', 'text-[18px]')
    cls = cls.replace('text-[19px]', 'text-[20px]')
    cls = cls.replace('text-[22px]', 'text-[24px]')
    return 'class="material-symbols-outlined ' + cls + '"'

pattern = re.compile(r'class="material-symbols-outlined ([^"]+)"')
new, n = pattern.subn(fix_class, src)
with io.open(path, "w", encoding="utf-8", newline="") as f:
    f.write(new)
print(f"{path}: {n} spans processed")
