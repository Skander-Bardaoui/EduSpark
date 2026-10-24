import re, io

path = r"coaching/templates/coaching/prof_dashboard.html"
with io.open(path, encoding="utf-8") as f:
    src = f.read()

repl = [
    # tiny badge/inline icons -> 16px
    ('class="material-symbols-outlined text-xs"', 'class="material-symbols-outlined text-[16px]"'),
    ('class="material-symbols-outlined text-sm"', 'class="material-symbols-outlined text-[16px]"'),
    ('class="material-symbols-outlined text-body-sm"', 'class="material-symbols-outlined text-[16px]"'),
    ('class="material-symbols-outlined text-body-md"', 'class="material-symbols-outlined text-[16px]"'),
    # inline 16px -> 18px
    ('class="material-symbols-outlined text-[16px]"', 'class="material-symbols-outlined text-[18px]"'),
]
for a, b in repl:
    n = src.count(a)
    src = src.replace(a, b)
    print(f"{n:2d}x  {a}  ->  {b}")

with io.open(path, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("done")
