import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { runYandexOfficeOAuth } from "./oauth.js";

const PROVIDER_ID = "yandex-office";

export default definePluginEntry({
  id: PROVIDER_ID,
  name: "Yandex Office",
  description: "Yandex Office OAuth helper plugin for shared skills",
  register(api) {
    api.registerProvider({
      id: PROVIDER_ID,
      label: "Yandex Office",
      docsPath: "/plugins/building-plugins",
      auth: [
        {
          id: "oauth",
          label: "Yandex Office OAuth",
          hint: "Browser sign-in via localhost callback",
          kind: "oauth",
          wizard: {
            choiceId: "yandex-office",
            choiceLabel: "Yandex Office OAuth",
            choiceHint: "Browser sign-in via localhost callback",
            groupId: "yandex-office",
            groupLabel: "Yandex Office",
            groupHint: "OAuth helper for shared Yandex skills",
          },
          run: async (ctx) => await runYandexOfficeOAuth(ctx),
        },
      ],
      catalog: {
        order: "simple",
        run: async () => null,
      },
    });
  },
});
