// frontend/src/api/categories.ts
import { apiFetch } from './client'
import type { Category } from '../types'

export const categoriesApi = {
  // The user's whole category library; an account uses the subset in its category_ids.
  list: () => apiFetch<Category[]>('/categories'),
}
