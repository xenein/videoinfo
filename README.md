# Was ist das hier?

Ein Tool, um Informationen für Quellenangaben, zum Beispiel für Live-Reaction-Formate zu Videos zu genieren.

## Wie geht das?

Das hier läuft https://videoinfo.elixirrlicht.dev/. Da kann man bisschen damit rumspielen, verschiedene Video-Links einfügen und schauen, was raus kommt. Oder ob was rauskommt.

Fancy wirds, wenn man das irgendwie mit streamer.bot oder in andere Setups mitintegriert. Sagen wir, wir brauchen Infos für dieses Video: `https://www.youtube.com/watch?v=dQw4w9WgXcQ` die kommen frei haus mit einem GET-Request an [https://videoinfo.elixirrlicht.dev/?link=https://www.youtube.com/watch?v=dQw4w9WgXcQ](https://videoinfo.elixirrlicht.dev/?link=https://www.youtube.com/watch?v=dQw4w9WgXcQ).

Das geht bisher für YouTube, für die ARD-Mediathek und für die ZDF-Mediathek.
