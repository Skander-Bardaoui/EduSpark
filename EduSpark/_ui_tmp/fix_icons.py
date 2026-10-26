import re
import sys

FILES = [
    "coaching/templates/coaching/prof_dashboard.html",
    "coaching/templates/coaching/prof_followup.html",
    "accounts/templates/accounts/prof_profile.html",
    "courses/templates/courses/prof_course.html",
    "exams/templates/exams/prof_corrections.html",
]

# Icon size normalization (only on lines that carry a material-symbols icon).
# Scale: 24px tiles / 20px sections / 18px actions / 16px inline / 14px badges.
REPLACEMENTS = [
    (r"text-\[28px\]", "text-[24px]"),
    (r"text-\[26px\]", "text-[24px]"),
    (r"text-\[22px\]", "text-[20px]"),
    (r"text-\[21px\]", "text-[20px]"),
    (r"text-\[19px\]", "text-[18px]"),
]

for path in FILES:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    changed = 0
    out = []
    for line in lines:
        new = line
        if "material-symbols-outlined" in line:
            for pat, rep in REPLACEMENTS:
                new = re.sub(pat, rep, new)
        if new != line:
            changed += 1
        out.append(new)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"{path}: {changed} lines changed")
