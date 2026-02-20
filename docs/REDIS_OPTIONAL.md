# Redis Optional Configuration

Redis caching is now **optional** in PyPNM GUI. The application will work perfectly fine without Redis.

## Why Make Redis Optional?

- **Simpler deployment**: No need to manage an additional service
- **Lower resource usage**: Reduces memory and CPU consumption
- **Easier development**: Start developing immediately without setup
- **Built-in caching**: The application uses in-memory caching when Redis is unavailable

## When to Use Redis?

Consider enabling Redis if you:
- Have **high traffic** with many concurrent users
- Need **persistent caching** across restarts
- Want to **share cache** between multiple app instances
- Have **large CMTS inventories** (hundreds of devices)

## Default Behavior (No Redis)

Without Redis, the application uses:
- **In-memory caching** with TTL (time-to-live)
- **Per-process cache** (not shared between workers)
- **Lost on restart** (cache cleared when app restarts)

This is sufficient for most deployments!

## How to Enable Redis (Optional)

### 1. Install Redis

**Docker:**
```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

**Ubuntu/Debian:**
```bash
sudo apt-get install redis-server
sudo systemctl start redis
```

**macOS:**
```bash
brew install redis
brew services start redis
```

### 2. Install Python Redis Package

Uncomment in `backend/requirements.txt`:
```python
redis>=5.0.0
```

Then reinstall:
```bash
pip install -r backend/requirements.txt
```

### 3. Configure Environment Variables

Add to your environment or `.env` file:
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 4. Enable in Docker Compose

Uncomment the Redis service in your docker-compose file:

**docker-compose.prod.yml:**
```yaml
services:
  gui-server-prod:
    environment:
      - REDIS_HOST=localhost
      - REDIS_PORT=6379
    depends_on:
      - redis-prod
  
  redis-prod:
    image: redis:7-alpine
    container_name: eve-li-redis-prod
    network_mode: host
    volumes:
      - redis-data-prod:/data
    restart: unless-stopped
    command: redis-server --appendonly yes

volumes:
  redis-data-prod:
    driver: local
```

## Verifying Redis Connection

If Redis is configured, you should see in the logs:
```
INFO: Redis cache available at localhost:6379
```

If Redis is unavailable:
```
INFO: Redis not configured, using in-memory cache
```

## Performance Comparison

| Scenario | Without Redis | With Redis |
|----------|--------------|------------|
| **First CMTS list load** | ~2-5 seconds | ~2-5 seconds |
| **Subsequent loads (cached)** | ~10-50ms | ~5-10ms |
| **Cache persistence** | Lost on restart | Persists across restarts |
| **Multi-worker support** | Separate cache per worker | Shared cache |
| **Memory usage** | Lower | Higher (Redis process) |

## Troubleshooting

### Redis Connection Failed

If you see errors like:
```
ERROR: Failed to connect to Redis at localhost:6379
```

**Solution**: Either install/start Redis or simply remove the `REDIS_HOST` and `REDIS_PORT` environment variables. The app will fall back to in-memory caching automatically.

### Redis Not Using Persistence

If Redis is not persisting data across restarts, ensure you're using:
```bash
redis-server --appendonly yes
```

## Summary

**Redis is completely optional**. The default configuration works great for most deployments. Only enable Redis if you specifically need its advanced features like persistence and shared caching.
