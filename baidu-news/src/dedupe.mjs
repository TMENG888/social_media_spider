export function normalizeTitleForMatch(value) {
  return String(value || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

export function normalizeContentForMatch(value) {
  return String(value || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

export function characterNgrams(value, size = 4) {
  const text = normalizeContentForMatch(value);
  if (!text) return new Set();
  if (text.length <= size) return new Set([text]);
  const grams = new Set();
  for (let index = 0; index <= text.length - size; index += 1) grams.add(text.slice(index, index + size));
  return grams;
}

export function diceSimilarity(left, right) {
  if (!left.size || !right.size) return 0;
  let intersection = 0;
  const smaller = left.size <= right.size ? left : right;
  const larger = left.size <= right.size ? right : left;
  for (const item of smaller) if (larger.has(item)) intersection += 1;
  return (2 * intersection) / (left.size + right.size);
}

export class ArticleDeduper {
  constructor(articles = [], options = {}) {
    this.threshold = Number(options.threshold ?? 0.5);
    this.gramSize = Number(options.gramSize ?? 4);
    this.minimumContentLength = Number(options.minimumContentLength ?? 100);
    this.articles = [];
    this.contentIndex = new Map();
    this.gramIndex = new Map();
    for (const article of articles) this.add(article);
  }

  add(article) {
    const comparable = {
      ...article,
      normalizedTitle: normalizeTitleForMatch(article.title),
      normalizedContent: normalizeContentForMatch(article.content),
      grams: characterNgrams(article.content, this.gramSize)
    };
    const index = this.articles.length;
    this.articles.push(comparable);
    if (comparable.normalizedContent) {
      if (!this.contentIndex.has(comparable.normalizedContent)) this.contentIndex.set(comparable.normalizedContent, []);
      this.contentIndex.get(comparable.normalizedContent).push(index);
    }
    for (const gram of comparable.grams) {
      if (!this.gramIndex.has(gram)) this.gramIndex.set(gram, []);
      this.gramIndex.get(gram).push(index);
    }
    return comparable;
  }

  find(article) {
    const normalizedTitle = normalizeTitleForMatch(article.title);
    const normalizedContent = normalizeContentForMatch(article.content);
    if (normalizedContent.length < this.minimumContentLength) return null;
    const exactMatchIndex = (this.contentIndex.get(normalizedContent) || []).find((index) => this.articles[index].url !== article.url);
    if (exactMatchIndex != null) {
      const matched = this.articles[exactMatchIndex];
      return { rule: "content_exact", similarity: 1, titleMatched: Boolean(normalizedTitle && normalizedTitle === matched.normalizedTitle), matched };
    }
    const grams = characterNgrams(normalizedContent, this.gramSize);
    const overlaps = new Map();
    for (const gram of grams) {
      for (const index of this.gramIndex.get(gram) || []) overlaps.set(index, (overlaps.get(index) || 0) + 1);
    }
    let best = null;
    for (const [index, intersection] of overlaps) {
      const candidate = this.articles[index];
      if (candidate.url === article.url || candidate.normalizedContent.length < this.minimumContentLength) continue;
      const maximumPossible = (2 * Math.min(grams.size, candidate.grams.size)) / (grams.size + candidate.grams.size);
      if (maximumPossible < this.threshold) continue;
      const similarity = (2 * intersection) / (grams.size + candidate.grams.size);
      if (similarity >= this.threshold && (!best || similarity > best.similarity)) best = { rule: "content_similarity", similarity, titleMatched: Boolean(normalizedTitle && normalizedTitle === candidate.normalizedTitle), matched: candidate };
    }
    return best;
  }
}
