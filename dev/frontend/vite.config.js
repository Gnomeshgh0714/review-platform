import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // #018 杂项d：host: 'localhost' 在 Node 17+ 下按 verbatim DNS 解析为 ::1，
    // 只绑 IPv6，127.0.0.1 访问不通（#011/#016 反复踩）。改为 true 监听全部
    // 地址（双栈），127.0.0.1 / localhost / [::1] 均可访问。
    host: true,
    proxy: {
      '/api': {
        // #018 杂项d：同理避免 Node 17+ 把 localhost 解析为 ::1 而 Django
        // runserver 默认只绑 127.0.0.1 —— 显式用 IPv4 回环地址，代理稳定
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  resolve: {
    alias: {
      '@': '/src'
    }
  }
})
