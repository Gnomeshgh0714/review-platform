import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        // 决策 #026（F-4）：构建拆包——原 index chunk 1250KB（gzip 406KB）
        // 超 1MB 告警，根因 main.js 全量引入 ElementPlus+图标注册与
        // echarts 路由分块不均。按依赖族拆 vendor，首屏业务代码回到合理量级。
        // 顺序敏感：echarts 判断必须在 vue 之前——vue-echarts 依赖 vue，
        // 若 vue 组先命中会把 vue-echarts 连带其 echarts 依赖误吞进 vendor-vue。
        // vue 组用「包名后紧跟路径分隔符」的精确判断，vue-echarts 不命中。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](echarts|vue-echarts|zrender)[\\/]/.test(id)) {
            return 'vendor-echarts'
          }
          if (/[\\/]node_modules[\\/](element-plus|@element-plus)[\\/]/.test(id)) {
            return 'vendor-element'
          }
          if (/[\\/]node_modules[\\/](@vue|vue|pinia)[\\/]/.test(id)) {
            return 'vendor-vue'
          }
          if (/[\\/]node_modules[\\/](axios|dayjs)[\\/]/.test(id)) {
            return 'vendor-utils'
          }
          return undefined
        },
      },
    },
  },
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
