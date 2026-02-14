import type { Lang } from "../types";

type DivineAliasGroup = {
  id: string;
  values: Record<
    Lang,
    {
      canonical: string;
      aliases: readonly string[];
    }
  >;
};

const DIVINE_ALIAS_GROUPS: readonly DivineAliasGroup[] = [
  {
    id: "god",
    values: {
      en: {
        canonical: "God",
        aliases: [
          "GOD",
          "god",
          "the LORD",
          "LORD",
          "the Lord",
          "Lord",
          "the LORD God",
          "LORD God",
          "the Lord GOD",
          "Lord GOD",
          "Adonai",
          "Hashem",
          "G-d",
          "Gd",
          "YHWH",
          "Jehovah",
        ],
      },
      he: {
        canonical: "אֱלֹהִים",
        aliases: [
          "אלוהים",
          "אֱלֹהִים",
          "אלהים",
          "אלקים",
          "אדני",
          "אדוני",
          "אֲדֹנָי",
          "אֲדֹנָי יְהוָה",
          "יְהוָה",
          "יְהֹוָה",
          "יְהוִה",
          "יהוה",
          "השם",
          "ה׳",
          "ה'",
          "יי",
        ],
      },
    },
  },
];

function normalizeAliasKey(text: string, lang: Lang): string {
  let s = text.toLowerCase();
  if (lang === "he") {
    s = s.replace(/[\u0591-\u05C7]/g, "");
    s = s.replace(/ה['׳]/g, "השם");
  }
  s = s.replace(/[^\w\u0590-\u05FF]+/g, " ");
  s = s.replace(/\s+/g, " ").trim();
  if (lang === "en") {
    s = s.replace(/^the\s+/, "");
  }
  return s;
}

const DIVINE_ALIAS_LOOKUP: Record<Lang, Map<string, DivineAliasGroup>> = {
  en: new Map<string, DivineAliasGroup>(),
  he: new Map<string, DivineAliasGroup>(),
};

for (const group of DIVINE_ALIAS_GROUPS) {
  for (const lang of ["en", "he"] as const) {
    const { canonical, aliases } = group.values[lang];
    DIVINE_ALIAS_LOOKUP[lang].set(normalizeAliasKey(canonical, lang), group);
    for (const alias of aliases) {
      DIVINE_ALIAS_LOOKUP[lang].set(normalizeAliasKey(alias, lang), group);
    }
  }
}

export function canonicalizeDivineName(value: string, lang: Lang): string | null {
  const key = normalizeAliasKey(value, lang);
  if (!key) return null;
  const group = DIVINE_ALIAS_LOOKUP[lang].get(key);
  return group ? group.values[lang].canonical : null;
}

export function normalizeDivineAlias(value: string, lang: Lang): string | null {
  const canonical = canonicalizeDivineName(value, lang);
  return canonical ? normalizeAliasKey(canonical, lang) : null;
}
