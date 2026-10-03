// Shared by the public search UI and its tests. This module never reads local data.
export function searchState(search, categories) {
 const params = new URLSearchParams(search);
 const requested = params.get('category') || '';
 return {
  query: (params.get('q') || '').trim().slice(0, 120),
  category: requested === 'uncategorized' || categories.some(item => item.id === requested) ? requested : '',
  featured: params.get('featured') === '1',
 };
}
export function selectPosts(posts, state) {
 const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase('zh-TW');
 const words = normalize(state.query).split(/\s+/).filter(Boolean);
 const matches = post => (!state.category || (state.category === 'uncategorized' ? !post.category : post.category === state.category)) &&
  (!state.featured || post.featured) && words.every(word => normalize([post.title, post.summary, post.body].join('\n')).includes(word));
 const results = posts.filter(matches);
 return state.featured ? results.sort((a, b) => a.featuredOrder - b.featuredOrder) : results;
}
export function searchUrl(base, state) {
 const params = new URLSearchParams();
 if (state.category) params.set('category', state.category);
 if (state.query) params.set('q', state.query);
 if (state.featured) params.set('featured', '1');
 return base + 'posts/' + (params.size ? '?' + params : '');
}
