# Yandex Search Region Codes

Region IDs for use with `--region` parameter.

## Major Cities (Russia)

| City | ID | Name (Russian) |
|------|----|----|
| Moscow | 213 | Москва |
| St. Petersburg | 2 | Санкт-Петербург |
| Novosibirsk | 65 | Новосибирск |
| Yekaterinburg | 54 | Екатеринбург |
| Kazan | 43 | Казань |
| Nizhny Novgorod | 47 | Нижний Новгород |
| Chelyabinsk | 56 | Челябинск |
| Samara | 51 | Самара |
| Omsk | 66 | Омск |
| Rostov-on-Don | 39 | Ростов-на-Дону |
| Ufa | 172 | Уфа |
| Krasnoyarsk | 62 | Красноярск |
| Voronezh | 193 | Воронеж |
| Perm | 50 | Пермь |
| Volgograd | 38 | Волгоград |

## Countries & Regions

| Region | ID | Name |
|--------|----|----|
| Russia | 225 | Россия |
| Ukraine | 187 | Украина |
| Belarus | 149 | Беларусь |
| Kazakhstan | 162 | Казахстан |
| Turkey | 983 | Турция |
| USA | 84 | США |
| United Kingdom | 102 | Великобритания |
| Germany | 96 | Германия |
| France | 124 | Франция |

## Federal Districts (Russia)

| District | ID | Name |
|----------|----|----|
| Central | 1 | Центральный |
| Northwestern | 10 | Северо-Западный |
| Southern | 26 | Южный |
| North Caucasian | 40 | Северо-Кавказский |
| Volga | 52 | Приволжский |
| Ural | 59 | Уральский |
| Siberian | 11316 | Сибирский |
| Far Eastern | 73 | Дальневосточный |

## Usage Examples

**Moscow region:**
```bash
python search.py "query" --region 213
```

**All of Russia:**
```bash
python search.py "query" --region 225
```

**Ukraine:**
```bash
python search.py "query" --region 187 --lang uk
```

## Notes

- Using broader regions (e.g., 225 for Russia) returns more results
- City-specific regions (e.g., 213 for Moscow) prioritize local content
- If unsure, omit `--region` to use default (Moscow)

## Finding Region IDs

To find a specific city's region ID:

1. Visit https://yandex.com/search/xml/region.xml
2. Search for the city name
3. Use the `id` attribute

Or use Yandex's region hierarchy:
https://yandex.com/dev/xml/doc/dg/reference/regions.html
