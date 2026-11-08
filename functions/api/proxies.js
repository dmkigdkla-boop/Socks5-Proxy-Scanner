/**
 * Cloudflare Pages Function - 代理 API
 * 路径: /api/proxies
 * 
 * 从 KV 读取代理列表并返回 JSON
 */

// CORS 头部配置
const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400', // 24 小时
};

/**
 * 处理 OPTIONS 请求（CORS 预检）
 */
function handleOptions() {
    return new Response(null, {
        status: 204,
        headers: corsHeaders
    });
}

/**
 * 处理 GET 请求 - 返回代理列表
 */
async function handleGet(context) {
    try {
        // 从 KV 读取代理数据
        const proxyData = await context.env.PROXY_POOL.get('current_proxies', 'json');

        // 如果数据不存在，返回空列表
        if (!proxyData) {
            return new Response(JSON.stringify({
                metadata: {
                    total: 0,
                    updated_at: null,
                    description: 'SOCKS5 代理列表'
                },
                proxies: []
            }), {
                status: 200,
                headers: {
                    'Content-Type': 'application/json',
                    ...corsHeaders
                }
            });
        }

        // Accept legacy exports as well as the current schema. This lets a Pages
        // deployment recover cleanly when an older value is still in KV.
        if (!proxyData.metadata) {
            proxyData.metadata = {
                total: proxyData.total_proxies || proxyData.proxies?.length || 0,
                updated_at: proxyData.timestamp || null,
                update_time_utc: proxyData.timestamp || null,
                description: 'SOCKS5 代理列表'
            };
        }

        // 返回代理数据
        return new Response(JSON.stringify(proxyData), {
            status: 200,
            headers: {
                'Content-Type': 'application/json; charset=utf-8',
                'Cache-Control': 'public, max-age=300', // 缓存 5 分钟
                ...corsHeaders
            }
        });

    } catch (error) {
        // 错误处理
        console.error('读取代理数据失败:', error);

        return new Response(JSON.stringify({
            error: 'Internal Server Error',
            message: '读取代理数据失败',
            metadata: {
                total: 0,
                updated_at: null,
                description: 'SOCKS5 代理列表'
            },
            proxies: []
        }), {
            status: 500,
            headers: {
                'Content-Type': 'application/json',
                ...corsHeaders
            }
        });
    }
}

/**
 * 主处理函数
 */
export async function onRequest(context) {
    const { request } = context;

    // 处理 OPTIONS 请求（CORS 预检）
    if (request.method === 'OPTIONS') {
        return handleOptions();
    }

    // 处理 GET 请求
    if (request.method === 'GET') {
        return await handleGet(context);
    }

    // 不支持的方法
    return new Response('Method Not Allowed', {
        status: 405,
        headers: corsHeaders
    });
}
