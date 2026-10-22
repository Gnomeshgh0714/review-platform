import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// 测试专用配置：与 vite.config.js 解耦，dev/build 行为零影响。
// 与 vite.config.js 的差异仅两处：
//   1. alias '@' 用文件系统绝对路径（node 测试环境无法解析 '/src' 这种根路径写法）
//   2. 声明 test 字段：happy-dom 环境（提供 localStorage 等浏览器 API）+ 就近放置的用例文件
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.js'],
  },
})
