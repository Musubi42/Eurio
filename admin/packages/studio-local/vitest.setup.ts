// jsdom n'implémente pas la mise en page : `scrollIntoView` n'existe pas sur
// ses éléments. La vue de lot l'appelle à chaque déplacement de curseur —
// sans ce polyfill, chaque test qui bouge le curseur lève un rejet non capté
// après coup, et vitest sort en échec sur des tests pourtant verts.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
