/**
 * Cloudflare Pages Function - 随机代理 API
 * 路径: /api/random
 * 
 * 从代理列表中随机返回一个代理
 */

const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
};

export async function onRequest(context) {
    const { request } = context;

    // 处理 OPTIONS 请求
    if (request.method === 'OPTIONS') {
        return new Response(null, {
            status: 204,
            headers: corsHeaders
        });
    }

    try {
        // 从 KV 读取代理数据
        const proxyData = await context.env.PROXY_POOL.get('current_proxies', 'json');

        if (!proxyData || !proxyData.proxies || proxyData.proxies.length === 0) {
            return new Response(JSON.stringify({
                error: 'No proxies available',
                message: '当前没有可用的代理'
            }), {
                status: 404,
                headers: {
                    'Content-Type': 'application/json',
                    ...corsHeaders
                }
            });
        }

        // 随机选择一个代理
        const randomProxy = proxyData.proxies[
            Math.floor(Math.random() * proxyData.proxies.length)
        ];
        const metadata = proxyData.metadata || {};
        const proxyAddress = randomProxy.proxy || `${randomProxy.ip}:${randomProxy.port}`;

        // 返回随机代理
        return new Response(JSON.stringify({
            proxy: proxyAddress,
            ip: randomProxy.ip,
            port: randomProxy.port,
            protocol: randomProxy.protocol || 'socks5',
            country: randomProxy.country,
            country_code: randomProxy.country_code,
            latency: randomProxy.latency ?? randomProxy.response_time ?? null,
            score: randomProxy.score,
            anonymity: randomProxy.anonymity || randomProxy.anonymity_level || 'unknown',
            metadata: {
                total_available: metadata.total || proxyData.total_proxies || proxyData.proxies.length,
                last_updated: metadata.updated_at || proxyData.timestamp || null
            }
        }), {
            status: 200,
            headers: {
                'Content-Type': 'application/json',
                'Cache-Control': 'no-cache', // 不缓存随机结果
                ...corsHeaders
            }
        });

    } catch (error) {
        console.error('获取随机代理失败:', error);

        return new Response(JSON.stringify({
            error: 'Internal Server Error',
            message: '获取随机代理失败'
        }), {
            status: 500,
            headers: {
                'Content-Type': 'application/json',
                ...corsHeaders
            }
        });
    }
}
