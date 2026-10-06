using Microsoft.Extensions.DependencyInjection;

namespace Pricing;

public static class PricingClientRegistration
{
    public static IServiceCollection AddPricingClient(this IServiceCollection services)
    {
        services.AddHttpClient<IPricingClient, PricingClient>(client =>
        {
            client.BaseAddress = new Uri("https://pricing.internal");
        });
        return services;
    }
}
