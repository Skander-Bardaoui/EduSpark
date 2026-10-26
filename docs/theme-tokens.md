# Tokens du thème clair / sombre

Généré depuis `EduSpark/static/theme/theme.css` (palette claire du portail enseignant ;
les portails admin, étudiant et les pages de connexion ont quelques nuances claires propres,
voir les blocs `:root[data-palette=…]`). Toutes les variables sont des triplets `R G B`.

## Échelle des surfaces sombres (élévation)

| Niveau | Token générique | Rôle Tailwind | Sombre |
|---|---|---|---|
| 0 | `--bg` | `background / surface` | `#0b0f18` |
| 1 | `--surface-1` | `surface-container-low` | `#121723` |
| 2 | `--surface-2` | `surface-container-lowest` | `#191f2c` |
| 3 | `--surface-3` | `surface-container` | `#1f2635` |
| 4 | `--surface-4` | `surface-container-high` | `#242c3d` |
| 5 | `--surface-5` | `surface-container-highest` | `#2a3244` |
| 6 | `--surface-6` | menus, modales, popovers | `#2f384b` |

## Tous les tokens Tailwind (`--md-*`)

| Token | Usage principal | Clair | Sombre |
|---|---|---|---|
| `background` | fond de page | `#fbf8ff` | `#0b0f18` |
| `error` | erreur | `#ba1a1a` | `#ffb6ad` |
| `error-container` | fond d'erreur | `#ffdad6` | `#502221` |
| `hero-from` | bandeau sombre (début) | `#002752` | `#172640` |
| `hero-to` | bandeau sombre (fin) | `#001a3f` | `#101a2d` |
| `hero-via` | bandeau sombre (milieu) | `#004191` | `#23385c` |
| `info` | information | `#4b41e1` | `#b2adfb` |
| `inverse-on-surface` |  | `#efefff` | `#191f2c` |
| `inverse-primary` |  | `#adc6ff` | `#004191` |
| `inverse-surface` |  | `#1f2d61` | `#e6eaf4` |
| `on-background` |  | `#06164b` | `#e6eaf4` |
| `on-error` |  | `#ffffff` | `#5e0808` |
| `on-error-container` |  | `#93000a` | `#ffd5d1` |
| `on-hero` | texte des bandeaux | `#ffffff` | `#e6eaf4` |
| `on-primary` | texte sur accent | `#ffffff` | `#0a1938` |
| `on-primary-container` |  | `#8db1ff` | `#0a1938` |
| `on-primary-fixed` |  | `#001a42` | `#d3e1fd` |
| `on-primary-fixed-variant` |  | `#004395` | `#b8cef9` |
| `on-secondary` |  | `#ffffff` | `#171249` |
| `on-secondary-container` |  | `#fffbff` | `#e7e5ff` |
| `on-secondary-fixed` |  | `#0f0069` | `#dad6ff` |
| `on-secondary-fixed-variant` |  | `#3323cc` | `#c1bbfb` |
| `on-success-container` |  | `#065f46` | `#b6edcd` |
| `on-surface` | texte principal | `#06164b` | `#e6eaf4` |
| `on-surface-variant` | texte secondaire | `#424754` | `#b6bdce` |
| `on-tertiary` |  | `#ffffff` | `#372806` |
| `on-tertiary-container` |  | `#facf74` | `#372806` |
| `on-tertiary-fixed` |  | `#261a00` | `#ffe6a8` |
| `on-tertiary-fixed-variant` |  | `#5c4300` | `#f6d88e` |
| `outline` | icônes et texte d'appoint | `#727785` | `#9ca3b4` |
| `outline-variant` | bordures | `#c3c6d3` | `#3f495f` |
| `primary` | accent, liens, boutons | `#004191` | `#a3c1fa` |
| `primary-container` | survol des boutons | `#004191` | `#c0d5fc` |
| `primary-fixed` | pastilles accentuées | `#d8e2ff` | `#223253` |
| `primary-fixed-dim` |  | `#aec6ff` | `#2f436a` |
| `scrim` | voile des modales | `#06164b` | `#04060b` |
| `secondary` |  | `#4b41e1` | `#b2adfb` |
| `secondary-container` |  | `#655dfb` | `#3e3894` |
| `secondary-fixed` |  | `#e2dfff` | `#2b284d` |
| `secondary-fixed-dim` |  | `#c3c0ff` | `#393663` |
| `success` | succès | `#15803d` | `#75d19c` |
| `success-container` |  | `#d1fae5` | `#1e3e2e` |
| `surface` | fond de page | `#fbf8ff` | `#0b0f18` |
| `surface-bright` |  | `#fbf8ff` | `#2a3244` |
| `surface-container` | conteneurs, puces | `#ecedff` | `#1f2635` |
| `surface-container-high` | survol, sélection, menus | `#e4e7ff` | `#242c3d` |
| `surface-container-highest` | accents de surface | `#dde1ff` | `#2a3244` |
| `surface-container-low` | zones en creux, champs | `#f3f2ff` | `#121723` |
| `surface-container-lowest` | cartes | `#ffffff` | `#191f2c` |
| `surface-dim` |  | `#d2d8ff` | `#080b12` |
| `surface-tint` |  | `#085ac0` | `#a3c1fa` |
| `surface-variant` |  | `#dde1ff` | `#2a3244` |
| `tertiary` |  | `#594100` | `#ecc879` |
| `tertiary-container` |  | `#594100` | `#e3bb63` |
| `tertiary-fixed` |  | `#ffdf9f` | `#43371e` |
| `tertiary-fixed-dim` |  | `#e6c277` | `#e2b95a` |
| `warning` | avertissement | `#d97706` | `#f6bd5a` |
| `warning-container` |  | `#fffbeb` | `#3d301a` |

## Ratios de contraste (WCAG AA)

Seuils : 4,5:1 pour le texte, 3:1 pour les icônes, composants et grands textes. ⚠ = sous le seuil
(uniquement des écarts du thème clair antérieurs au thème, conservés pour ne pas changer le rendu).

| Texte | Fond | Seuil | Clair (prof) | Sombre |
|---|---|---|---|---|
| `on-surface` | `background` | 4.5 | #06164b / #fbf8ff — **16.32** | #e6eaf4 / #0b0f18 — **15.92** |
| `on-surface` | `surface-container-low` | 4.5 | #06164b / #f3f2ff — **15.49** | #e6eaf4 / #121723 — **14.87** |
| `on-surface` | `surface-container-lowest` | 4.5 | #06164b / #ffffff — **17.16** | #e6eaf4 / #191f2c — **13.69** |
| `on-surface` | `surface-container` | 4.5 | #06164b / #ecedff — **14.81** | #e6eaf4 / #1f2635 — **12.57** |
| `on-surface` | `surface-container-high` | 4.5 | #06164b / #e4e7ff — **14.03** | #e6eaf4 / #242c3d — **11.61** |
| `on-surface` | `surface-container-highest` | 4.5 | #06164b / #dde1ff — **13.31** | #e6eaf4 / #2a3244 — **10.65** |
| `on-surface-variant` | `background` | 4.5 | #424754 / #fbf8ff — **8.83** | #b6bdce / #0b0f18 — **10.18** |
| `on-surface-variant` | `surface-container-low` | 4.5 | #424754 / #f3f2ff — **8.38** | #b6bdce / #121723 — **9.52** |
| `on-surface-variant` | `surface-container-lowest` | 4.5 | #424754 / #ffffff — **9.29** | #b6bdce / #191f2c — **8.76** |
| `on-surface-variant` | `surface-container` | 4.5 | #424754 / #ecedff — **8.02** | #b6bdce / #1f2635 — **8.05** |
| `on-surface-variant` | `surface-container-high` | 4.5 | #424754 / #e4e7ff — **7.60** | #b6bdce / #242c3d — **7.43** |
| `on-surface-variant` | `surface-container-highest` | 4.5 | #424754 / #dde1ff — **7.20** | #b6bdce / #2a3244 — **6.81** |
| `primary` | `background` | 4.5 | #004191 / #fbf8ff — **9.23** | #a3c1fa / #0b0f18 — **10.56** |
| `primary` | `surface-container-low` | 4.5 | #004191 / #f3f2ff — **8.76** | #a3c1fa / #121723 — **9.86** |
| `primary` | `surface-container-lowest` | 4.5 | #004191 / #ffffff — **9.70** | #a3c1fa / #191f2c — **9.08** |
| `primary` | `surface-container` | 4.5 | #004191 / #ecedff — **8.37** | #a3c1fa / #1f2635 — **8.34** |
| `primary` | `surface-container-high` | 4.5 | #004191 / #e4e7ff — **7.93** | #a3c1fa / #242c3d — **7.70** |
| `primary` | `surface-container-highest` | 4.5 | #004191 / #dde1ff — **7.52** | #a3c1fa / #2a3244 — **7.06** |
| `secondary` | `background` | 4.5 | #4b41e1 / #fbf8ff — **6.36** | #b2adfb / #0b0f18 — **9.37** |
| `secondary` | `surface-container-low` | 4.5 | #4b41e1 / #f3f2ff — **6.03** | #b2adfb / #121723 — **8.75** |
| `secondary` | `surface-container-lowest` | 4.5 | #4b41e1 / #ffffff — **6.68** | #b2adfb / #191f2c — **8.06** |
| `secondary` | `surface-container` | 4.5 | #4b41e1 / #ecedff — **5.77** | #b2adfb / #1f2635 — **7.40** |
| `secondary` | `surface-container-high` | 4.5 | #4b41e1 / #e4e7ff — **5.46** | #b2adfb / #242c3d — **6.83** |
| `secondary` | `surface-container-highest` | 4.5 | #4b41e1 / #dde1ff — **5.18** | #b2adfb / #2a3244 — **6.27** |
| `error` | `background` | 4.5 | #ba1a1a / #fbf8ff — **6.14** | #ffb6ad / #0b0f18 — **11.45** |
| `error` | `surface-container-low` | 4.5 | #ba1a1a / #f3f2ff — **5.83** | #ffb6ad / #121723 — **10.70** |
| `error` | `surface-container-lowest` | 4.5 | #ba1a1a / #ffffff — **6.46** | #ffb6ad / #191f2c — **9.85** |
| `error` | `surface-container` | 4.5 | #ba1a1a / #ecedff — **5.58** | #ffb6ad / #1f2635 — **9.05** |
| `error` | `surface-container-high` | 4.5 | #ba1a1a / #e4e7ff — **5.28** | #ffb6ad / #242c3d — **8.35** |
| `error` | `surface-container-highest` | 4.5 | #ba1a1a / #dde1ff — **5.01** | #ffb6ad / #2a3244 — **7.66** |
| `outline` | `background` | 3.0 | #727785 / #fbf8ff — **4.26** | #9ca3b4 / #0b0f18 — **7.59** |
| `outline` | `surface-container-lowest` | 3.0 | #727785 / #ffffff — **4.47** | #9ca3b4 / #191f2c — **6.53** |
| `outline` | `surface-container` | 3.0 | #727785 / #ecedff — **3.86** | #9ca3b4 / #1f2635 — **5.99** |
| `tertiary` | `background` | 3.0 | #594100 / #fbf8ff — **9.16** | #ecc879 / #0b0f18 — **11.96** |
| `tertiary` | `surface-container-lowest` | 3.0 | #594100 / #ffffff — **9.63** | #ecc879 / #191f2c — **10.29** |
| `tertiary` | `surface-container` | 3.0 | #594100 / #ecedff — **8.31** | #ecc879 / #1f2635 — **9.45** |
| `success` | `background` | 3.0 | #15803d / #fbf8ff — **4.77** | #75d19c / #0b0f18 — **10.36** |
| `success` | `surface-container-lowest` | 3.0 | #15803d / #ffffff — **5.02** | #75d19c / #191f2c — **8.92** |
| `success` | `surface-container` | 3.0 | #15803d / #ecedff — **4.33** | #75d19c / #1f2635 — **8.19** |
| `warning` | `background` | 3.0 | #d97706 / #fbf8ff — **3.03** | #f6bd5a / #0b0f18 — **11.27** |
| `warning` | `surface-container-lowest` | 3.0 | #d97706 / #ffffff — **3.19** | #f6bd5a / #191f2c — **9.69** |
| `warning` | `surface-container` | 3.0 | #d97706 / #ecedff — **2.75** ⚠ | #f6bd5a / #1f2635 — **8.90** |
| `info` | `background` | 3.0 | #4b41e1 / #fbf8ff — **6.36** | #b2adfb / #0b0f18 — **9.37** |
| `info` | `surface-container-lowest` | 3.0 | #4b41e1 / #ffffff — **6.68** | #b2adfb / #191f2c — **8.06** |
| `info` | `surface-container` | 3.0 | #4b41e1 / #ecedff — **5.77** | #b2adfb / #1f2635 — **7.40** |
| `on-primary` | `primary` | 4.5 | #ffffff / #004191 — **9.70** | #0a1938 / #a3c1fa — **9.57** |
| `on-primary` | `primary-container` | 4.5 | #ffffff / #004191 — **9.70** | #0a1938 / #c0d5fc — **11.72** |
| `primary` | `primary-fixed` | 4.5 | #004191 / #d8e2ff — **7.50** | #a3c1fa / #223253 — **7.01** |
| `on-surface` | `primary-fixed` | 4.5 | #06164b / #d8e2ff — **13.27** | #e6eaf4 / #223253 — **10.58** |
| `on-secondary` | `secondary` | 4.5 | #ffffff / #4b41e1 — **6.68** | #171249 / #b2adfb — **8.42** |
| `on-secondary-container` | `secondary-container` | 4.5 | #fffbff / #655dfb — **4.54** | #e7e5ff / #3e3894 — **7.76** |
| `on-secondary-fixed` | `secondary-fixed` | 4.5 | #0f0069 / #e2dfff — **13.26** | #dad6ff / #2b284d — **9.94** |
| `on-tertiary-fixed` | `tertiary-fixed` | 4.5 | #261a00 / #ffdf9f — **13.26** | #ffe6a8 / #43371e — **9.50** |
| `on-tertiary-container` | `tertiary-container` | 4.5 | #facf74 / #594100 — **6.53** | #372806 / #e3bb63 — **7.87** |
| `on-error` | `error` | 4.5 | #ffffff / #ba1a1a — **6.46** | #5e0808 / #ffb6ad — **8.29** |
| `on-error-container` | `error-container` | 4.5 | #93000a / #ffdad6 — **7.24** | #ffd5d1 / #502221 — **9.86** |
| `on-hero` | `hero-from` | 4.5 | #ffffff / #002752 — **14.87** | #e6eaf4 / #172640 — **12.57** |
| `on-hero` | `hero-via` | 4.5 | #ffffff / #004191 — **9.70** | #e6eaf4 / #23385c — **9.73** |
| `on-hero` | `hero-to` | 4.5 | #ffffff / #001a3f — **17.22** | #e6eaf4 / #101a2d — **14.44** |
| `inverse-on-surface` | `inverse-surface` | 4.5 | #efefff / #1f2d61 — **11.49** | #191f2c / #e6eaf4 — **13.69** |
| `on-success-container` | `success-container` | 4.5 | #065f46 / #d1fae5 — **6.78** | #b6edcd / #1e3e2e — **8.96** |
| `tertiary` | `warning-container` | 4.5 | #594100 / #fffbeb — **9.29** | #ecc879 / #3d301a — **8.01** |
| `warning` | `warning-container` | 3.0 | #d97706 / #fffbeb — **3.07** | #f6bd5a / #3d301a — **7.55** |
| `primary` | `background` | 3.0 | #004191 / #fbf8ff — **9.23** | #a3c1fa / #0b0f18 — **10.56** |
