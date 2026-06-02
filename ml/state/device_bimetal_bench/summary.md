# Bench bimétal — chemin DEVICE (baseline Phase 1)

Généré 2026-06-01 22:00:55

- Captures device : `../debug_pull/eval_real/20260529_162919/eval_real`
- Cohort CSV : `state/cohort_csvs/mix-zone-17.csv`

## Part A — distribution d'inférence (captures device + oracle Otsu)

- Captures avec détection device + oracle résolu : **107**
- Undercrops suspects (r_dev/r_oracle < 0.85) : **12 (11 %)**
- Oracle Otsu non concluant : **43**
- Échecs détection device (no circle / unreadable) : **1**

**r_dev/r_oracle** : min=0.748 p25=0.893 med=0.915 p75=0.933 max=1.089

| class | step | r_dev | r_oracle | ratio | method | susp | file |
|---|---|---|---|---|---|---|---|
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | dim_plain | 102 | 136 | 0.75 | hough_strict | ⚠ | `A_at-2005-2eur-50th-anniversary-of-the-aus__dim-plain.jpg` |
| fi-2017-2eur-100-years-of-independence | dim_plain | 94 | 121 | 0.78 | hough_strict | ⚠ | `A_fi-2017-2eur-100-years-of-independence__dim-plain.jpg` |
| de-2020-2eur-50-years-since-the-kniefall-von-warschau | dim_plain | 84 | 107 | 0.78 | hough_strict | ⚠ | `A_de-2020-2eur-50-years-since-the-kniefall__dim-plain.jpg` |
| it-2016-2eur-550-years-since-the-death-of-donatello | dim_plain | 88 | 112 | 0.78 | hough_strict | ⚠ | `A_it-2016-2eur-550-years-since-the-death-o__dim-plain.jpg` |
| fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | dim_plain | 93 | 118 | 0.79 | hough_strict | ⚠ | `A_fi-2016-2eur-100th-anniversary-of-the-bi__dim-plain.jpg` |
| be-2008-2eur-standard | dim_plain | 87 | 110 | 0.79 | hough_strict | ⚠ | `A_be-2008-2eur-standard__dim-plain.jpg` |
| be-2011-2eur-1st-centenary-of-the-international-womens-day | dim_plain | 98 | 123 | 0.79 | hough_strict | ⚠ | `A_be-2011-2eur-1st-centenary-of-the-intern__dim-plain.jpg` |
| es-2016-2eur-old-city-of-segovia-and-its-aqueduct | dim_plain | 105 | 132 | 0.80 | hough_strict | ⚠ | `A_es-2016-2eur-old-city-of-segovia-and-its__dim-plain.jpg` |
| es-1999-2eur-standard | dim_plain | 86 | 107 | 0.80 | hough_strict | ⚠ | `A_es-1999-2eur-standard__dim-plain.jpg` |
| be-2007-2eur-standard | dim_plain | 87 | 108 | 0.80 | hough_strict | ⚠ | `A_be-2007-2eur-standard__dim-plain.jpg` |
| fr-2018-2eur-simone-veil | dim_plain | 97 | 116 | 0.83 | hough_strict | ⚠ | `A_fr-2018-2eur-simone-veil__dim-plain.jpg` |
| be-2007-2eur-standard | daylight_plain | 80 | 94 | 0.85 | hough_strict | ⚠ | `A_be-2007-2eur-standard__daylight-plain.jpg` |
| ad-2014-2eur-standard | bright_textured | 83 | — | n/a | hough_strict |  | `A_ad-2014-2eur-standard__bright-textured.jpg` |
| ad-2014-2eur-standard | dim_plain | 89 | — | n/a | hough_strict |  | `A_ad-2014-2eur-standard__dim-plain.jpg` |
| ad-2014-2eur-standard-1st-type | bright_plain_p1 | 87 | — | n/a | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-plain-p1.jpg` |
| ad-2014-2eur-standard-1st-type | bright_plain_p2 | 89 | — | n/a | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-plain-p2.jpg` |
| ad-2014-2eur-standard-1st-type | bright_plain_p3 | 83 | — | n/a | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-plain-p3.jpg` |
| ad-2014-2eur-standard-1st-type | bright_plain | 83 | — | n/a | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-plain.jpg` |
| at-2002-2eur-standard | bright_textured | 79 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard__bright-textured.jpg` |
| at-2002-2eur-standard-1st-map | bright_plain_p2 | 213 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-plain-p2.jpg` |
| at-2002-2eur-standard-1st-map | bright_plain_p3 | 241 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-plain-p3.jpg` |
| at-2002-2eur-standard-1st-map | bright_plain | 78 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-plain.jpg` |
| at-2002-2eur-standard-1st-map | bright_textured_p1 | 73 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-textured-p1.jpg` |
| at-2002-2eur-standard-1st-map | bright_textured_p2 | 195 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-textured-p2.jpg` |
| at-2002-2eur-standard-1st-map | bright_textured_p3 | 72 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-textured-p3.jpg` |
| at-2002-2eur-standard-1st-map | bright_textured | 74 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__bright-textured.jpg` |
| at-2002-2eur-standard-1st-map | dim_p1 | 72 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__dim-p1.jpg` |
| at-2002-2eur-standard-1st-map | dim | 76 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__dim.jpg` |
| at-2002-2eur-standard-1st-map | partial_shadow | 79 | — | n/a | hough_strict |  | `A_at-2002-2eur-standard-1st-map__partial-shadow.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | bright_plain | 81 | — | n/a | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__bright-plain.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | bright_textured | 81 | — | n/a | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__bright-textured.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | dim | 81 | — | n/a | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__dim.jpg` |
| be-2007-2eur-standard | bright_textured | 83 | — | n/a | hough_strict |  | `A_be-2007-2eur-standard__bright-textured.jpg` |
| be-2008-2eur-standard | bright_textured | 73 | — | n/a | hough_strict |  | `A_be-2008-2eur-standard__bright-textured.jpg` |
| be-2011-2eur-1st-centenary-of-the-international-womens-day | bright_textured | 89 | — | n/a | hough_strict |  | `A_be-2011-2eur-1st-centenary-of-the-intern__bright-textured.jpg` |
| de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | bright_plain | 76 | — | n/a | hough_strict |  | `A_de-2007-2eur-schwerin-castle-mecklenburg__bright-plain.jpg` |
| de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | bright_textured | 72 | — | n/a | hough_strict |  | `A_de-2007-2eur-schwerin-castle-mecklenburg__bright-textured.jpg` |
| de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | close_plain | 73 | — | n/a | hough_strict |  | `A_de-2007-2eur-schwerin-castle-mecklenburg__close-plain.jpg` |
| de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | daylight_plain | 74 | — | n/a | hough_strict |  | `A_de-2007-2eur-schwerin-castle-mecklenburg__daylight-plain.jpg` |
| de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | dim_plain | 73 | — | n/a | hough_strict |  | `A_de-2007-2eur-schwerin-castle-mecklenburg__dim-plain.jpg` |
| de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | tilt_plain | 72 | — | n/a | hough_strict |  | `A_de-2007-2eur-schwerin-castle-mecklenburg__tilt-plain.jpg` |
| de-2020-2eur-50-years-since-the-kniefall-von-warschau | bright_textured | 80 | — | n/a | hough_strict |  | `A_de-2020-2eur-50-years-since-the-kniefall__bright-textured.jpg` |
| es-1999-2eur-standard | bright_textured | 78 | — | n/a | hough_strict |  | `A_es-1999-2eur-standard__bright-textured.jpg` |
| es-2016-2eur-old-city-of-segovia-and-its-aqueduct | bright_textured | 101 | — | n/a | hough_strict |  | `A_es-2016-2eur-old-city-of-segovia-and-its__bright-textured.jpg` |
| fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | bright_textured | 79 | — | n/a | hough_strict |  | `A_fi-2016-2eur-100th-anniversary-of-the-bi__bright-textured.jpg` |
| fi-2017-2eur-100-years-of-independence | bright_textured | 89 | — | n/a | hough_strict |  | `A_fi-2017-2eur-100-years-of-independence__bright-textured.jpg` |
| fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | bright_textured | 89 | — | n/a | hough_strict |  | `A_fr-2008-2eur-french-presidency-of-the-co__bright-textured.jpg` |
| fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | dim_plain | 98 | — | n/a | hough_strict |  | `A_fr-2008-2eur-french-presidency-of-the-co__dim-plain.jpg` |
| fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | bright_textured | 81 | — | n/a | hough_strict |  | `A_fr-2016-2eur-100-years-since-the-birth-o__bright-textured.jpg` |
| fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | dim_plain | 96 | — | n/a | hough_strict |  | `A_fr-2016-2eur-100-years-since-the-birth-o__dim-plain.jpg` |
| fr-2018-2eur-simone-veil | bright_textured | 81 | — | n/a | hough_strict |  | `A_fr-2018-2eur-simone-veil__bright-textured.jpg` |
| it-2016-2eur-2200-years-since-the-death-of-plautus | bright_textured | 78 | — | n/a | hough_strict |  | `A_it-2016-2eur-2200-years-since-the-death-__bright-textured.jpg` |
| it-2016-2eur-2200-years-since-the-death-of-plautus | dim_plain | 96 | — | n/a | hough_strict |  | `A_it-2016-2eur-2200-years-since-the-death-__dim-plain.jpg` |
| it-2016-2eur-550-years-since-the-death-of-donatello | bright_textured | 85 | — | n/a | hough_strict |  | `A_it-2016-2eur-550-years-since-the-death-o__bright-textured.jpg` |
| mt-2008-2eur-standard | bright_textured | 91 | — | n/a | hough_strict |  | `A_mt-2008-2eur-standard__bright-textured.jpg` |
| it-2016-2eur-550-years-since-the-death-of-donatello | daylight_plain | 93 | 108 | 0.85 | hough_strict |  | `A_it-2016-2eur-550-years-since-the-death-o__daylight-plain.jpg` |
| it-2016-2eur-2200-years-since-the-death-of-plautus | daylight_plain | 84 | 97 | 0.86 | hough_strict |  | `A_it-2016-2eur-2200-years-since-the-death-__daylight-plain.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | oblique | 61 | 70 | 0.86 | hough_loose |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__oblique.jpg` |
| be-2008-2eur-standard | close_plain | 108 | 124 | 0.87 | hough_strict |  | `A_be-2008-2eur-standard__close-plain.jpg` |
| at-2002-2eur-standard | tilt_plain | 84 | 95 | 0.88 | hough_strict |  | `A_at-2002-2eur-standard__tilt-plain.jpg` |
| ad-2014-2eur-standard-1st-type | bright_textured_p3 | 76 | 86 | 0.88 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-textured-p3.jpg` |
| it-2016-2eur-2200-years-since-the-death-of-plautus | close_plain | 105 | 119 | 0.88 | hough_strict |  | `A_it-2016-2eur-2200-years-since-the-death-__close-plain.jpg` |
| be-2011-2eur-1st-centenary-of-the-international-womens-day | bright_plain | 80 | 90 | 0.88 | hough_strict |  | `A_be-2011-2eur-1st-centenary-of-the-intern__bright-plain.jpg` |
| be-2007-2eur-standard | bright_plain | 85 | 96 | 0.88 | hough_strict |  | `A_be-2007-2eur-standard__bright-plain.jpg` |
| ad-2014-2eur-standard-1st-type | bright_textured_p1 | 77 | 86 | 0.89 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-textured-p1.jpg` |
| ad-2014-2eur-standard-1st-type | dim_p2 | 78 | 87 | 0.89 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__dim-p2.jpg` |
| fi-2017-2eur-100-years-of-independence | close_plain | 99 | 111 | 0.89 | hough_strict |  | `A_fi-2017-2eur-100-years-of-independence__close-plain.jpg` |
| fr-2007-2eur-standard | daylight_plain | 79 | 88 | 0.89 | hough_strict |  | `A_fr-2007-2eur-standard__daylight-plain.jpg` |
| be-2008-2eur-standard | bright_plain | 73 | 81 | 0.89 | hough_strict |  | `A_be-2008-2eur-standard__bright-plain.jpg` |
| be-2011-2eur-1st-centenary-of-the-international-womens-day | tilt_plain | 99 | 110 | 0.89 | hough_strict |  | `A_be-2011-2eur-1st-centenary-of-the-intern__tilt-plain.jpg` |
| es-1999-2eur-standard | tilt_plain | 78 | 87 | 0.89 | hough_strict |  | `A_es-1999-2eur-standard__tilt-plain.jpg` |
| fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | daylight_plain | 80 | 89 | 0.89 | hough_strict |  | `A_fr-2008-2eur-french-presidency-of-the-co__daylight-plain.jpg` |
| ad-2014-2eur-standard | tilt_plain | 87 | 97 | 0.89 | hough_strict |  | `A_ad-2014-2eur-standard__tilt-plain.jpg` |
| fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | daylight_plain | 88 | 98 | 0.90 | hough_strict |  | `A_fr-2016-2eur-100-years-since-the-birth-o__daylight-plain.jpg` |
| mt-2008-2eur-standard | dim_plain | 98 | 109 | 0.90 | hough_strict |  | `A_mt-2008-2eur-standard__dim-plain.jpg` |
| ad-2014-2eur-standard-1st-type | partial_shadow_p3 | 74 | 82 | 0.90 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__partial-shadow-p3.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | close_plain | 105 | 116 | 0.90 | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__close-plain.jpg` |
| fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | bright_plain | 77 | 85 | 0.90 | hough_strict |  | `A_fi-2016-2eur-100th-anniversary-of-the-bi__bright-plain.jpg` |
| fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | bright_plain | 86 | 95 | 0.90 | hough_strict |  | `A_fr-2008-2eur-french-presidency-of-the-co__bright-plain.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | tilt_plain | 85 | 94 | 0.90 | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__tilt-plain.jpg` |
| es-2016-2eur-old-city-of-segovia-and-its-aqueduct | bright_plain | 73 | 80 | 0.90 | hough_strict |  | `A_es-2016-2eur-old-city-of-segovia-and-its__bright-plain.jpg` |
| ad-2014-2eur-standard-1st-type | partial_shadow_p1 | 74 | 81 | 0.90 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__partial-shadow-p1.jpg` |
| de-2020-2eur-50-years-since-the-kniefall-von-warschau | close_plain | 105 | 116 | 0.90 | hough_strict |  | `A_de-2020-2eur-50-years-since-the-kniefall__close-plain.jpg` |
| ad-2014-2eur-standard-1st-type | dim | 82 | 90 | 0.91 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__dim.jpg` |
| fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | close_plain | 107 | 117 | 0.91 | hough_strict |  | `A_fi-2016-2eur-100th-anniversary-of-the-bi__close-plain.jpg` |
| fr-2018-2eur-simone-veil | tilt_plain | 89 | 97 | 0.91 | hough_strict |  | `A_fr-2018-2eur-simone-veil__tilt-plain.jpg` |
| ad-2014-2eur-standard-1st-type | partial_shadow_p2 | 75 | 82 | 0.91 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__partial-shadow-p2.jpg` |
| at-2002-2eur-standard | close_plain | 116 | 127 | 0.91 | hough_strict |  | `A_at-2002-2eur-standard__close-plain.jpg` |
| be-2011-2eur-1st-centenary-of-the-international-womens-day | daylight_plain | 97 | 106 | 0.91 | hough_strict |  | `A_be-2011-2eur-1st-centenary-of-the-intern__daylight-plain.jpg` |
| ad-2014-2eur-standard-1st-type | partial_shadow | 74 | 81 | 0.91 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__partial-shadow.jpg` |
| at-2002-2eur-standard | daylight_plain | 77 | 84 | 0.91 | hough_strict |  | `A_at-2002-2eur-standard__daylight-plain.jpg` |
| es-2016-2eur-old-city-of-segovia-and-its-aqueduct | tilt_plain | 78 | 85 | 0.91 | hough_strict |  | `A_es-2016-2eur-old-city-of-segovia-and-its__tilt-plain.jpg` |
| fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | close_plain | 111 | 121 | 0.91 | hough_strict |  | `A_fr-2008-2eur-french-presidency-of-the-co__close-plain.jpg` |
| ad-2014-2eur-standard-1st-type | dim_p3 | 80 | 87 | 0.91 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__dim-p3.jpg` |
| be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait | bright_plain | 66 | 72 | 0.91 | hough_loose |  | `A_be-2007-2eur-standard-albert-ii-2nd-map-__bright-plain.jpg` |
| fr-2018-2eur-simone-veil | daylight_plain | 84 | 91 | 0.91 | hough_strict |  | `A_fr-2018-2eur-simone-veil__daylight-plain.jpg` |
| it-2016-2eur-550-years-since-the-death-of-donatello | tilt_plain | 92 | 100 | 0.92 | hough_strict |  | `A_it-2016-2eur-550-years-since-the-death-o__tilt-plain.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | daylight_plain | 93 | 101 | 0.92 | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__daylight-plain.jpg` |
| fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | close_plain | 106 | 115 | 0.92 | hough_strict |  | `A_fr-2016-2eur-100-years-since-the-birth-o__close-plain.jpg` |
| mt-2008-2eur-standard | tilt_plain | 100 | 109 | 0.92 | hough_strict |  | `A_mt-2008-2eur-standard__tilt-plain.jpg` |
| fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | tilt_plain | 91 | 99 | 0.92 | hough_strict |  | `A_fr-2008-2eur-french-presidency-of-the-co__tilt-plain.jpg` |
| es-2016-2eur-old-city-of-segovia-and-its-aqueduct | daylight_plain | 106 | 115 | 0.92 | hough_strict |  | `A_es-2016-2eur-old-city-of-segovia-and-its__daylight-plain.jpg` |
| fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | daylight_plain | 85 | 92 | 0.92 | hough_strict |  | `A_fi-2016-2eur-100th-anniversary-of-the-bi__daylight-plain.jpg` |
| fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | tilt_plain | 86 | 93 | 0.92 | hough_strict |  | `A_fi-2016-2eur-100th-anniversary-of-the-bi__tilt-plain.jpg` |
| mt-2008-2eur-standard | bright_plain | 100 | 108 | 0.92 | hough_strict |  | `A_mt-2008-2eur-standard__bright-plain.jpg` |
| mt-2008-2eur-standard | daylight_plain | 102 | 111 | 0.92 | hough_strict |  | `A_mt-2008-2eur-standard__daylight-plain.jpg` |
| es-1999-2eur-standard | daylight_plain | 80 | 86 | 0.92 | hough_strict |  | `A_es-1999-2eur-standard__daylight-plain.jpg` |
| fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | bright_plain | 86 | 93 | 0.92 | hough_strict |  | `A_fr-2016-2eur-100-years-since-the-birth-o__bright-plain.jpg` |
| be-2007-2eur-standard | tilt_plain | 92 | 99 | 0.92 | hough_strict |  | `A_be-2007-2eur-standard__tilt-plain.jpg` |
| be-2008-2eur-standard | daylight_plain | 79 | 85 | 0.92 | hough_strict |  | `A_be-2008-2eur-standard__daylight-plain.jpg` |
| fr-2007-2eur-standard | tilt_plain | 109 | 118 | 0.92 | hough_strict |  | `A_fr-2007-2eur-standard__tilt-plain.jpg` |
| fi-2017-2eur-100-years-of-independence | bright_plain | 80 | 86 | 0.92 | hough_strict |  | `A_fi-2017-2eur-100-years-of-independence__bright-plain.jpg` |
| fr-2018-2eur-simone-veil | bright_plain | 87 | 94 | 0.92 | hough_strict |  | `A_fr-2018-2eur-simone-veil__bright-plain.jpg` |
| fi-2017-2eur-100-years-of-independence | daylight_plain | 93 | 100 | 0.92 | hough_strict |  | `A_fi-2017-2eur-100-years-of-independence__daylight-plain.jpg` |
| ad-2014-2eur-standard | daylight_plain | 89 | 96 | 0.93 | hough_strict |  | `A_ad-2014-2eur-standard__daylight-plain.jpg` |
| fi-2017-2eur-100-years-of-independence | tilt_plain | 102 | 110 | 0.93 | hough_strict |  | `A_fi-2017-2eur-100-years-of-independence__tilt-plain.jpg` |
| it-2016-2eur-2200-years-since-the-death-of-plautus | bright_plain | 81 | 87 | 0.93 | hough_strict |  | `A_it-2016-2eur-2200-years-since-the-death-__bright-plain.jpg` |
| de-2020-2eur-50-years-since-the-kniefall-von-warschau | daylight_plain | 85 | 91 | 0.93 | hough_strict |  | `A_de-2020-2eur-50-years-since-the-kniefall__daylight-plain.jpg` |
| ad-2014-2eur-standard-1st-type | dim_p1 | 82 | 88 | 0.93 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__dim-p1.jpg` |
| fr-2007-2eur-standard | dim_plain | 91 | 97 | 0.93 | hough_strict |  | `A_fr-2007-2eur-standard__dim-plain.jpg` |
| fr-2007-2eur-standard | close_plain | 104 | 111 | 0.93 | hough_strict |  | `A_fr-2007-2eur-standard__close-plain.jpg` |
| ad-2014-2eur-standard | bright_plain | 84 | 90 | 0.93 | hough_strict |  | `A_ad-2014-2eur-standard__bright-plain.jpg` |
| it-2016-2eur-550-years-since-the-death-of-donatello | close_plain | 109 | 116 | 0.93 | hough_strict |  | `A_it-2016-2eur-550-years-since-the-death-o__close-plain.jpg` |
| fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | tilt_plain | 73 | 78 | 0.93 | hough_strict |  | `A_fr-2016-2eur-100-years-since-the-birth-o__tilt-plain.jpg` |
| mt-2008-2eur-standard | close_plain | 113 | 121 | 0.93 | hough_strict |  | `A_mt-2008-2eur-standard__close-plain.jpg` |
| at-2002-2eur-standard | dim_plain | 84 | 89 | 0.94 | hough_strict |  | `A_at-2002-2eur-standard__dim-plain.jpg` |
| ad-2014-2eur-standard | close_plain | 120 | 128 | 0.94 | hough_strict |  | `A_ad-2014-2eur-standard__close-plain.jpg` |
| ad-2014-2eur-standard-1st-type | bright_textured | 84 | 89 | 0.94 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-textured.jpg` |
| ad-2014-2eur-standard-1st-type | bright_textured_p2 | 83 | 88 | 0.94 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__bright-textured-p2.jpg` |
| be-2011-2eur-1st-centenary-of-the-international-womens-day | close_plain | 110 | 117 | 0.94 | hough_strict |  | `A_be-2011-2eur-1st-centenary-of-the-intern__close-plain.jpg` |
| es-1999-2eur-standard | close_plain | 117 | 124 | 0.94 | hough_strict |  | `A_es-1999-2eur-standard__close-plain.jpg` |
| es-2016-2eur-old-city-of-segovia-and-its-aqueduct | close_plain | 110 | 117 | 0.94 | hough_strict |  | `A_es-2016-2eur-old-city-of-segovia-and-its__close-plain.jpg` |
| fr-2007-2eur-standard | bright_plain | 89 | 94 | 0.94 | hough_strict |  | `A_fr-2007-2eur-standard__bright-plain.jpg` |
| fr-2018-2eur-simone-veil | close_plain | 126 | 134 | 0.94 | hough_strict |  | `A_fr-2018-2eur-simone-veil__close-plain.jpg` |
| be-2007-2eur-standard | close_plain | 85 | 90 | 0.94 | hough_strict |  | `A_be-2007-2eur-standard__close-plain.jpg` |
| be-2008-2eur-standard | tilt_plain | 86 | 91 | 0.94 | hough_strict |  | `A_be-2008-2eur-standard__tilt-plain.jpg` |
| fr-2007-2eur-standard | bright_textured | 93 | 98 | 0.94 | hough_strict |  | `A_fr-2007-2eur-standard__bright-textured.jpg` |
| de-2020-2eur-50-years-since-the-kniefall-von-warschau | bright_plain | 78 | 82 | 0.95 | hough_strict |  | `A_de-2020-2eur-50-years-since-the-kniefall__bright-plain.jpg` |
| it-2016-2eur-550-years-since-the-death-of-donatello | bright_plain | 79 | 83 | 0.95 | hough_strict |  | `A_it-2016-2eur-550-years-since-the-death-o__bright-plain.jpg` |
| it-2016-2eur-2200-years-since-the-death-of-plautus | tilt_plain | 85 | 89 | 0.95 | hough_strict |  | `A_it-2016-2eur-2200-years-since-the-death-__tilt-plain.jpg` |
| de-2020-2eur-50-years-since-the-kniefall-von-warschau | tilt_plain | 84 | 88 | 0.95 | hough_strict |  | `A_de-2020-2eur-50-years-since-the-kniefall__tilt-plain.jpg` |
| at-2002-2eur-standard | bright_plain | 91 | 93 | 0.97 | hough_strict |  | `A_at-2002-2eur-standard__bright-plain.jpg` |
| ad-2014-2eur-standard-1st-type | oblique_p1 | 72 | 73 | 0.98 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__oblique-p1.jpg` |
| ad-2014-2eur-standard-1st-type | oblique | 73 | 74 | 0.98 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__oblique.jpg` |
| es-1999-2eur-standard | bright_plain | 72 | 72 | 1.00 | hough_strict |  | `A_es-1999-2eur-standard__bright-plain.jpg` |
| ad-2014-2eur-standard-1st-type | oblique_p2 | 72 | 72 | 1.00 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__oblique-p2.jpg` |
| ad-2014-2eur-standard-1st-type | oblique_p3 | 72 | 71 | 1.00 | hough_strict |  | `A_ad-2014-2eur-standard-1st-type__oblique-p3.jpg` |
| be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait | bright_textured | 76 | 72 | 1.05 | hough_strict |  | `A_be-2007-2eur-standard-albert-ii-2nd-map-__bright-textured.jpg` |
| at-2002-2eur-standard-1st-map | oblique | 80 | 73 | 1.08 | hough_strict |  | `A_at-2002-2eur-standard-1st-map__oblique.jpg` |
| at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | partial_shadow | 78 | 71 | 1.09 | hough_strict |  | `A_at-2005-2eur-50th-anniversary-of-the-aus__partial-shadow.jpg` |
| at-2002-2eur-standard-1st-map | bright_plain_p1 | — | — | — | — | err | no circle |

## Part B — isolation du guard (studio vs device, pixels identiques)

- Pièces cohort : **17**
- Studio contour fiable (guard actif) : **16** (les autres 1 ont fallback → device, divergence non mesurable)
- Divergences device inner-ring (device/studio < 0.85 sur guard actif) : **0 / 16** (0 %)

| numista | nom | studio_r | device_r | dev/studio | studio_method | device_method | diverge | file |
|---|---|---|---|---|---|---|---|---|
| 64 | at-2002-2eur-standard-1st-map | 776 | 719 | 0.93 | contour | hough_strict |  | `B_64.jpg` |
| 2201 | State of Mecklenburg-Vorpommern | 1198 | 1116 | 0.93 | contour | hough_strict |  | `B_2201.jpg` |
| 19734 | 100th International Women's Day | 1299 | 1286 | 0.99 | contour | hough_strict |  | `B_19734.jpg` |
| 88 | es-1999-2eur-standard-juan-carlos- | 1408 | 1394 | 0.99 | contour | hough_strict |  | `B_88.jpg` |
| 141382 | Simone Veil | 400 | 396 | 0.99 | contour | hough_strict |  | `B_141382.jpg` |
| 84714 | 2200th anniversary of the death of | 650 | 646 | 0.99 | contour | hough_strict |  | `B_84714.jpg` |
| 68395 | ad-2014-2eur-standard-1st-type | 753 | 749 | 0.99 | contour | hough_strict |  | `B_68395.jpg` |
| 6292 | be-2007-2eur-standard-albert-ii-2n | 781 | 777 | 0.99 | contour | hough_strict |  | `B_6292.jpg` |
| 113429 | 100 years of independence | 1256 | 1250 | 0.99 | contour | hough_strict |  | `B_113429.jpg` |
| 3561 | French Presidency of the Council o | 1250 | 1244 | 0.99 | contour | hough_strict |  | `B_3561.jpg` |
| 2193 | 50th anniversary of the Austrian S | 1354 | 1348 | 1.00 | contour | hough_strict |  | `B_2193.jpg` |
| 81058 | Old Town of Segovia and its Aquedu | 853 | 850 | 1.00 | contour | hough_strict |  | `B_81058.jpg` |
| 93999 | 100th anniversary of the birth of  | 1253 | 1248 | 1.00 | contour | hough_strict |  | `B_93999.jpg` |
| 91431 | 100th anniversary of the birth of  | 1258 | 1253 | 1.00 | contour | hough_strict |  | `B_91431.jpg` |
| 134283 | 100th anniversary of the end of th | 608 | 606 | 1.00 | contour | hough_strict |  | `B_134283.jpg` |
| 226447 | German-Polish Reconciliation | 494 | 494 | 1.00 | contour_fallback:hough_strict | hough_strict |  | `B_226447.jpg` |
| 82330 | 550th anniversary of the death of  | 1041 | 1043 | 1.00 | contour | hough_strict |  | `B_82330.jpg` |
