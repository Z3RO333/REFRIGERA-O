# Login Microsoft no Azure

Este guia mostra como configurar autenticação Microsoft em uma aplicação hospedada no Azure sem expor informações reais de ambiente.

## Azure App Registration

No Azure Portal, em **Microsoft Entra ID > App registrations > sua aplicação**:

1. Abra **Authentication**.
2. Adicione uma plataforma **Web**.
3. Cadastre o Redirect URI da aplicação:

```text
https://seu-app.azurewebsites.net/api/v1/auth/microsoft/callback
```

4. Em **Certificates & secrets**, crie um Client secret.
5. Armazene os valores somente nas configurações seguras do ambiente:

```text
MICROSOFT_TENANT_ID
MICROSOFT_CLIENT_ID
MICROSOFT_CLIENT_SECRET
```

## App Service Settings

Exemplo de configuração:

```env
MICROSOFT_AUTH_ENABLED=true
MICROSOFT_TENANT_ID=<tenant-id>
MICROSOFT_CLIENT_ID=<application-client-id>
MICROSOFT_CLIENT_SECRET=<client-secret>
MICROSOFT_REDIRECT_URI=https://seu-app.azurewebsites.net/api/v1/auth/microsoft/callback
MICROSOFT_ALLOWED_DOMAINS=empresa.com.br
MICROSOFT_AUTO_CREATE_USERS=true
MICROSOFT_DEFAULT_ROLE=VIEWER
POST_LOGIN_REDIRECT_URL=https://seu-app.azurewebsites.net/dashboard
ALLOWED_ORIGINS=https://seu-app.azurewebsites.net
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
```

Também configure os valores reais exclusivamente no ambiente seguro:

```env
SECRET_KEY=<valor-forte-com-32-ou-mais-caracteres>
DATABASE_URL=<url-do-banco>
REDIS_URL=<url-do-redis>
```

## Segurança

- Nunca versione Client Secrets, tokens ou URLs privadas de banco.
- Prefira Azure App Service Settings, Key Vault ou outro gerenciador de segredos.
- Use apenas valores fictícios em documentação pública e arquivos `.env.example`.
