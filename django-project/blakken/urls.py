"""
URL configuration for Blakken project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from .api import (
    create_management_category, create_management_dish, create_management_menu,
    customer_session, logout_tokens, management_category, management_dish,
    management_menu_content, management_menus, management_order_status, management_shop_status,
    management_orders, management_restaurants, obtain_tokens, public_default_menu,
    public_menu, public_menus, public_restaurant_status, refresh_tokens, register_restaurant,
    set_management_default_menu,
)
from .views import (
    auth, delete_page, dish_detail, dish_list, index, job_results, menu_pages, move_dish,
    move_page, page_visibility, restaurant_signup,
)
from .orders import (
    OrderAuthenticationForm, create_order, customer_order_auth, customer_orders,
    management_order_auth, order_list, orders_page, order_status, shop_status,
)

urlpatterns = [
    path('_nested_admin/', include('nested_admin.urls')),
    path('admin/', admin.site.urls),
    path('register/', restaurant_signup, name='restaurant-signup'),
    path('api/v1/auth/register/', register_restaurant, name='api-register'),
    path('api/v1/auth/token/', obtain_tokens, name='api-token'),
    path('api/v1/auth/refresh/', refresh_tokens, name='api-refresh'),
    path('api/v1/auth/logout/', logout_tokens, name='api-logout'),
    path('api/v1/customer/session/', customer_session, name='customer-session'),
    path('api/v1/management/restaurants/', management_restaurants, name='management-restaurants'),
    path('api/v1/management/restaurants/<uuid:appid>/orders/', management_orders, name='management-orders'),
    path('api/v1/management/restaurants/<uuid:appid>/orders/<int:order_id>/status/', management_order_status, name='management-order-status'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/', management_menus, name='management-menus'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/create/', create_management_menu, name='management-menu-create'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/<int:menu_id>/content/', management_menu_content, name='management-menu-content'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/<int:menu_id>/categories/', create_management_category, name='management-category-create'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/<int:menu_id>/categories/<int:category_id>/', management_category, name='management-category'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/<int:menu_id>/categories/<int:category_id>/dishes/', create_management_dish, name='management-dish-create'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/<int:menu_id>/dishes/<int:dish_id>/', management_dish, name='management-dish'),
    path('api/v1/management/restaurants/<uuid:appid>/menus/<int:menu_id>/default/', set_management_default_menu, name='management-menu-default'),
    path('api/v1/management/restaurants/<uuid:appid>/shop-status/', shop_status, name='management-shop-status'),
    path('api/v1/management/restaurants/<uuid:appid>/shop/', management_shop_status, name='management-shop-api'),
    path('api/v1/restaurants/<uuid:appid>/menus/', public_menus, name='public-menus'),
    path('api/v1/restaurants/<uuid:appid>/menus/default/', public_default_menu, name='public-default-menu'),
    path('api/v1/restaurants/<uuid:appid>/menus/<int:menu_id>/', public_menu, name='public-menu'),
    path('api/v1/restaurants/<uuid:appid>/shop-status/', public_restaurant_status, name='restaurant-shop-status'),
    path('api/v1/restaurants/<uuid:appid>/menus/<int:menu_id>/orders/', create_order, name='restaurant-create-order'),
    path('internal/auth/', auth, name='auth'),
    path('internal/order-auth/', customer_order_auth, name='customer-order-auth'),
    path('internal/management-order-auth/', management_order_auth, name='management-order-auth'),
    path('jobs/results/', job_results, name='job-results'),
    path('shop/status/', shop_status, name='shop-status'),
    path('orders/', orders_page, name='orders'),
    path('orders/login/', LoginView.as_view(
        template_name='orders_login.html', authentication_form=OrderAuthenticationForm,
        next_page='orders',
    ), name='orders-login'),
    path('orders/logout/', LogoutView.as_view(next_page='orders-login'), name='orders-logout'),
    path('orders/data/', order_list, name='order-list'),
    path('orders/mine/', customer_orders, name='customer-orders'),
    path('orders/<int:order_id>/status/', order_status, name='order-status'),
    path('menus/<int:menu_id>/pages/', menu_pages, name='menu-pages'),
    path('menus/<int:menu_id>/dishes/<int:dish_id>/', dish_detail, name='dish-detail'),
    path('menus/<int:menu_id>/pages/<int:page_id>/dishes/', dish_list, name='dish-list'),
    path('menus/<int:menu_id>/pages/<int:page_id>/move/', move_page, name='move-page'),
    path('menus/<int:menu_id>/pages/<int:page_id>/visibility/', page_visibility, name='page-visibility'),
    path('menus/<int:menu_id>/pages/<int:page_id>/', delete_page, name='delete-page'),
    path('menus/<int:menu_id>/dishes/<int:dish_id>/move/', move_dish, name='move-dish'),
    path('', index, name='index'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
