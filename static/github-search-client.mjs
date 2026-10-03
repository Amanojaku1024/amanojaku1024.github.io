import { searchState, selectPosts, searchUrl } from './github-search.mjs';

const form = document.querySelector('main form.post-search');
const section = document.getElementById('all-posts');
const filters = document.querySelector('main nav.filters');
if (form && section && filters) {
 try {
  const response = await fetch(new URL('./posts-index.json', import.meta.url));
  if (!response.ok) throw new Error('search index unavailable');
  const index = await response.json();
  const input = form.querySelector('input[type="search"]');
  const heading = section.querySelector('h2');
  const count = section.querySelector('.section-note');
  const list = document.createElement('ul');
  const original = section.querySelector('ul.post-list');
  list.className = 'post-list';
  // Reuse Astro's existing scoped styling and server-rendered card markup.
  if (original) for (const attribute of original.attributes) list.setAttribute(attribute.name, attribute.value);
  const empty = document.createElement('p');
  empty.className = 'empty';
  const emptySample = section.querySelector('.empty');
  if (emptySample) for (const attribute of emptySample.attributes) empty.setAttribute(attribute.name, attribute.value);
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.style.cssText = 'font-size:.875rem;color:var(--gray-300);margin-bottom:1.5rem;overflow-wrap:anywhere';
  filters.after(status);
  let state;
  const filterLinks = Array.from(filters.querySelectorAll('a')).map(link => {
   const params = new URL(link.href).searchParams;
   return { link, kind: params.get('featured') === '1' ? 'featured' : params.has('category') ? 'category' : 'all', category: params.get('category') || '' };
  });
  const apply = () => {
   state = searchState(location.search, index.categories);
   const results = selectPosts(index.posts, state);
   input.value = state.query;
   for (const name of ['category', 'featured']) {
    form.querySelectorAll(`input[name="${name}"]`).forEach(item => item.remove());
    const value = name === 'category' ? state.category : state.featured ? '1' : '';
    if (value) { const hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = name; hidden.value = value; form.append(hidden); }
   }
   const category = index.categories.find(item => item.id === state.category)?.name || '未分類';
   heading.textContent = state.query ? '搜尋結果' : state.featured ? '精選貼文' : state.category ? category : '全部貼文';
   count.textContent = `${results.length} 篇紀錄`;
   list.innerHTML = results.map(post => post.card).join('');
   section.querySelector('ul.post-list, p.empty')?.remove();
   empty.textContent = state.query ? '找不到符合的貼文，試試其他關鍵字或切換分類。' : state.featured ? '目前沒有符合的精選文章，可以切換「全部」繼續閱讀。' : '這裡還沒有已發布的文章。';
   section.append(results.length ? list : empty);
   status.replaceChildren();
   status.hidden = !state.query;
   if (state.query) {
    status.append(document.createTextNode(`「${state.query}」的搜尋結果 · ${results.length} 篇 `));
    const clear = document.createElement('a');
    clear.textContent = '清除搜尋'; clear.href = searchUrl(index.base, { ...state, query: '' });
    clear.style.cssText = 'display:inline-flex;align-items:center;min-height:44px;margin-left:.8rem';
    status.append(clear);
   }
   for (const { link, kind, category } of filterLinks) {
    const target = kind === 'all' ? { ...state, category: '', featured: false } : kind === 'featured' ? { ...state, featured: !state.featured } : { ...state, category };
    link.href = searchUrl(index.base, target);
    const active = kind === 'all' ? !state.category && !state.featured : kind === 'featured' ? state.featured : state.category === category;
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    const badge = link.querySelector('span');
    if (badge) badge.textContent = String(kind === 'all' ? index.posts.length : kind === 'featured' ? selectPosts(index.posts, { ...state, featured: true }).length : selectPosts(index.posts, { query: '', category, featured: state.featured }).length);
   }
  };
  const navigate = url => { history.pushState(null, '', url); apply(); };
  form.addEventListener('submit', event => { event.preventDefault(); navigate(searchUrl(index.base, { ...state, query: input.value.trim().slice(0,120) })); });
  for (const element of [filters, status]) element.addEventListener('click', event => {
   const link = event.target.closest('a');
   if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
   event.preventDefault(); navigate(link.href);
  });
  window.addEventListener('popstate', apply);
  apply();
 } catch {
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  status.textContent = '搜尋資料暫時無法讀取，請重新整理；下方仍可閱讀全部文章。';
  form.after(status);
 }
}
