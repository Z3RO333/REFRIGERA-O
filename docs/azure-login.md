# Login Microsoft no Azure

Dominio da demo:

```text
https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net
```

## Azure App Registration

No Azure Portal, em Microsoft Entra ID > App registrations > sua aplicacao:

1. Abra Authentication.
2. Adicione uma plataforma Web.
3. Cadastre o Redirect URI:

```text
https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net/api/v1/auth/microsoft/callback
```

4. Em Certificates & secrets, crie um Client secret.
5. Guarde estes valores para o App Service:

```text
MICROSOFT_TENANT_ID
MICROSOFT_CLIENT_ID
MICROSOFT_CLIENT_SECRET
```

## App Service Settings

No App Service, em Configuration > Application settings, configure:

```env
MICROSOFT_AUTH_ENABLED=true
MICROSOFT_TENANT_ID=<tenant-id>
MICROSOFT_CLIENT_ID=<application-client-id>
MICROSOFT_CLIENT_SECRET=<client-secret>
MICROSOFT_REDIRECT_URI=https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net/api/v1/auth/microsoft/callback
MICROSOFT_ALLOWED_DOMAINS=bemol.com.br
MICROSOFT_AUTO_CREATE_USERS=true
MICROSOFT_DEFAULT_ROLE=VIEWER
POST_LOGIN_REDIRECT_URL=https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net/dashboard
ALLOWED_ORIGINS=https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
```

Tambem configure valores reais para:

```env
SECRET_KEY=<valor-forte-com-32-ou-mais-caracteres>
DATABASE_URL=<url-do-banco>
REDIS_URL=<url-do-redis>
```

## Teste

Depois do deploy, abra:

```text
https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net/api/v1/auth/methods
```

Resposta esperada:

```json
{"microsoft":true}
```

Depois acesse:

```text
https://xn--monitoramentorefrigerao-b9fef2c4d2heeja2-vld1o.brazilsouth-01.azurewebsites.net/login
```

O botao Entrar com Microsoft deve aparecer.
