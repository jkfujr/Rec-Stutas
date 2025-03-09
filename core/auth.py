import jwt
from typing import Optional
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from core.logs import log
from functools import wraps

logger = log()

class Auth:
    """认证"""    
    def __init__(self, config):
        auth_config = config.get("AUTH", {})
        self.enabled = auth_config.get("ENABLE", False)
        self.secret_key = auth_config.get("AUTH_KEY", "114514")
        self.token_expire_minutes = auth_config.get("AUTH_KEY_EXPIRE", 60 * 24)
        self.users = {}
        user_configs = auth_config.get("AUTH_USER", {})
        
        for username, user_data in user_configs.items():
            actual_username = user_data.get("USER", username)
            password = user_data.get("PASS", "")
            if password:
                self.users[actual_username] = password
        
        logger.info(f"[Auth] 已加载 {len(self.users)} 个用户账号")
        logger.debug(f"[Auth] 认证已{'启用' if self.enabled else '禁用'}")
    
    def authenticate_user(self, username: str, password: str) -> bool:
        """验证用户名和密码"""
        if not self.enabled:
            return False
            
        return username in self.users and self.users[username] == password
    
    def create_token(self, username: str) -> str:
        """创建 token"""
        expire = datetime.utcnow() + timedelta(minutes=self.token_expire_minutes)
        token_data = {
            "sub": username,
            "exp": expire
        }
        return jwt.encode(token_data, self.secret_key, algorithm="HS256")
    
    def verify_token(self, token: str) -> Optional[str]:
        """验证 token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token已过期")
        except jwt.exceptions.DecodeError:
            raise HTTPException(status_code=401, detail="无效的Token")
        except Exception as e:
            logger.error(f"Token验证失败: {str(e)}")
            raise HTTPException(status_code=401, detail=f"Token验证失败: {str(e)}")
        
auth_scheme = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(auth_scheme)) -> str:
    """验证用户"""
    from main import config, auth
    
    if not config.get("AUTH", {}).get("ENABLE", False):
        return "anonymous"
        
    username = auth.verify_token(credentials.credentials)
    if not username:
        raise HTTPException(status_code=401, detail="认证失败")
    return username

def requires_auth(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        from main import config
        
        if not config.get("AUTH", {}).get("ENABLE", False):
            return await func(*args, **kwargs)
            
        if not kwargs.get("current_user"):
            raise HTTPException(status_code=401, detail="需要认证")
        return await func(*args, **kwargs)
    return wrapper 